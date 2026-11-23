#!/bin/bash
# First boot of the PrestoSports runner (infra/bootstrap/runner.tf). Installs
# the GitHub Actions runner and the idle stop. It does not register the
# runner: that takes a one-hour token only Daniel can mint, handed in with
# touchline-register-runner (docs: guides/collect-in-actions).
set -euo pipefail
exec > >(tee -a /var/log/touchline-runner-setup.log) 2>&1

# First, before anything that can fail: first-boot setup runs once, so a
# machine whose setup broke must still be able to stop itself.
# Idle stop: the workflow starts this machine just before the presto job is
# queued, and the machine stops itself once no job has run for a while. A
# stopped instance costs only its disk. /run is cleared on every boot, so each
# start gets the full grace again.
cat > /usr/local/bin/touchline-idle-stop <<'EOF'
#!/bin/bash
set -euo pipefail
count_file=/run/touchline-idle-minutes
# Registered: stop after ${idle_minutes} idle minutes. Not registered yet: leave an
# hour for the registration, then stop rather than run up a bill.
limit=${idle_minutes}
[ -f /opt/actions-runner/.runner ] || limit=60
if pgrep -f Runner.Worker >/dev/null; then
  echo 0 > "$count_file"
  exit 0
fi
count=$(( $(cat "$count_file" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$count_file"
if [ "$count" -ge "$limit" ]; then
  logger -t touchline-idle-stop "no job for $count minutes; stopping"
  systemctl poweroff
fi
EOF
chmod 755 /usr/local/bin/touchline-idle-stop

cat > /etc/systemd/system/touchline-idle-stop.service <<'EOF'
[Unit]
Description=Stop the PrestoSports runner when no job is running

[Service]
Type=oneshot
ExecStart=/usr/local/bin/touchline-idle-stop
EOF

cat > /etc/systemd/system/touchline-idle-stop.timer <<'EOF'
[Unit]
Description=Check once a minute whether the PrestoSports runner is idle

[Timer]
OnBootSec=60
OnUnitActiveSec=60
AccuracySec=5

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now touchline-idle-stop.timer

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q curl jq tar git ca-certificates unzip

id runner >/dev/null 2>&1 || useradd --create-home --shell /bin/bash runner

# The newest runner release: GitHub refuses runners that fall too far behind,
# and the runner keeps itself current after this.
install -d -o runner -g runner /opt/actions-runner
cd /opt/actions-runner
if [ ! -x ./config.sh ]; then
  tag=$(curl -fsSI https://github.com/actions/runner/releases/latest | tr -d '\r' | sed -n 's#^[Ll]ocation: .*/tag/v##p')
  [ -n "$tag" ] || { echo "could not resolve the runner release"; exit 1; }
  curl -fsSL -o /tmp/runner.tgz "https://github.com/actions/runner/releases/download/v$tag/actions-runner-linux-x64-$tag.tar.gz"
  sudo -u runner tar -xzf /tmp/runner.tgz
  rm -f /tmp/runner.tgz
  ./bin/installdependencies.sh
fi

cat > /usr/local/bin/touchline-register-runner <<'EOF'
#!/bin/bash
# touchline-register-runner <registration token>
# Registers this machine to the rib with the label `presto` and starts the
# runner as a service. Safe to run again with a fresh token.
set -euo pipefail
token="$${1:?usage: touchline-register-runner <registration token>}"
cd /opt/actions-runner
if [ -f .service ]; then
  ./svc.sh stop || true
  ./svc.sh uninstall || true
fi
# config.sh refuses a machine that still holds an earlier registration, so
# drop the local half of it; --replace takes over the same name on GitHub.
rm -f .runner .credentials .credentials_rsaparams
sudo -u runner ./config.sh --unattended --replace \
  --url "https://github.com/${repo}" --token "$token" \
  --name touchline-presto-aws --labels presto --work _work
./svc.sh install runner
# After every job the runner calls the cleanup below; it reads the hook from
# its .env file when the service starts. The runner refuses a hook whose
# name does not end in .sh, and fails the job, so the name matters. The line
# is rewritten, not only added, so registering again corrects an old one.
touch .env
sed -i '/^ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/d' .env
echo 'ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/usr/local/bin/touchline-job-cleanup.sh' >> .env
chown runner:runner .env
./svc.sh start
echo "registered"
EOF
chmod 755 /usr/local/bin/touchline-register-runner

# After every job, clear the job's checkout, so no code or work home outlives
# the job that used it. The runner empties its own temporary folder, where
# the work home is unpacked, at the start of the next job. Never fails a job.
cat > /usr/local/bin/touchline-job-cleanup.sh <<'EOF'
#!/bin/bash
work=/opt/actions-runner/_work
for dir in "$work"/*/; do
  case "$(basename "$dir")" in
    _*) ;;
    *) find "$dir" -mindepth 1 -delete 2>/dev/null ;;
  esac
done
exit 0
EOF
chmod 755 /usr/local/bin/touchline-job-cleanup.sh

echo "setup complete"

"""Fetch a URL list politely and save what came back (D3 discovery, temporary).

Reads spikes/d3/urls.txt ("name url" per line). One worker per host at a time,
SPACING seconds between requests to a host, up to WORKERS hosts at once.
Reads each host's robots.txt first and skips a URL it disallows for
"Touchline". Writes spikes/d3/out/<name> and spikes/d3/out/index-<round>.json.
Never retries a refusal.
"""
import json, os, time, pathlib, threading, urllib.request, urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

UA = "Mozilla/5.0 (Touchline educational/research collector; +https://github.com/ed-insights-ai/keelson-rib-touchline)"
SPACING = float(os.environ.get("SPACING", "5"))
WORKERS = int(os.environ.get("WORKERS", "12"))
here = pathlib.Path(__file__).parent
out = here / "out"
out.mkdir(exist_ok=True)
lines = [l.split(None, 1) for l in (here / "urls.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
round_name = (here / "urls.txt").read_text().splitlines()[0].lstrip("# ").split(":")[0].strip().replace(" ", "-")[:40] or "round"
by_host = defaultdict(list)
for name, url in lines:
    by_host[urlparse(url).netloc.lower()].append((name, url.strip()))
index, lock = {}, threading.Lock()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), r.geturl(), None
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", url, None
    except Exception as e:  # noqa: BLE001
        return None, b"", url, repr(e)


def host_job(host, items):
    scheme = urlparse(items[0][1]).scheme
    status, body, _, err = get(f"{scheme}://{host}/robots.txt")
    rp = None
    if status and 200 <= status < 300:
        rp = RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines())
    for i, (name, url) in enumerate(items):
        time.sleep(SPACING)
        if rp is not None and not rp.can_fetch("Touchline", url):
            rec = {"url": url, "robots": "disallowed"}
            body = b""
        else:
            status, body, final, err = get(url)
            rec = {"url": url, "status": status, "final": final, "bytes": len(body)}
            if err:
                rec["error"] = err
            if status in (403, 429):
                rec["stopped_host"] = True
        (out / name).write_bytes(body)
        with lock:
            index[name] = rec
        print(name, rec, flush=True)
        if rec.get("stopped_host"):
            for name2, url2 in items[i + 1:]:
                with lock:
                    index[name2] = {"url": url2, "skipped": f"host answered {status}"}
            return


with ThreadPoolExecutor(WORKERS) as pool:
    for host, items in by_host.items():
        pool.submit(host_job, host, items)
(out / f"index-{round_name}.json").write_text(json.dumps(index, indent=1))
(out / "index.json").write_text(json.dumps(index, indent=1))

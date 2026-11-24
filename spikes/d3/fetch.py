"""Fetch a short list of URLs politely and save what came back (D3 discovery).

Reads spikes/d3/urls.txt (one "name url" per line), fetches each with the
collector's honest User-Agent, at least SPACING seconds apart overall, and
writes spikes/d3/out/<name> plus an index of status codes. Never retries a
refusal.
"""
import json, os, sys, time, pathlib, urllib.request, urllib.error

UA = "Mozilla/5.0 (Touchline educational/research collector; +https://github.com/ed-insights-ai/keelson-rib-touchline)"
SPACING = float(os.environ.get("SPACING", "3"))
here = pathlib.Path(__file__).parent
out = here / "out"
out.mkdir(exist_ok=True)
index = {}
last = 0.0
for line in (here / "urls.txt").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name, url = line.split(None, 1)
    wait = SPACING - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    last = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            index[name] = {"url": url, "status": r.status, "final": r.geturl(), "bytes": len(body), "type": r.headers.get("content-type")}
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        index[name] = {"url": url, "status": e.code, "bytes": len(body)}
    except Exception as e:  # noqa: BLE001
        body = b""
        index[name] = {"url": url, "error": repr(e)}
    (out / name).write_bytes(body)
    print(name, index[name], flush=True)
(out / "index.json").write_text(json.dumps(index, indent=1))

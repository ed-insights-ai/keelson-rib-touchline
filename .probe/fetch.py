"""Temporary: fetch pages from a hosted runner into .probe/pages (thread scratch)."""
import hashlib, json, pathlib, sys, time
import requests
s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0 (Touchline educational/research collector)"
out = pathlib.Path(".probe/pages"); out.mkdir(parents=True, exist_ok=True)
index = []
for url in pathlib.Path(".probe/urls.txt").read_text().split():
    name = hashlib.sha1(url.encode()).hexdigest()[:12]
    try:
        r = s.get(url, timeout=40)
        (out / f"{name}.html").write_bytes(r.content)
        index.append({"url": url, "file": name, "status": r.status_code, "final": r.url, "len": len(r.content),
                      "history": [h.status_code for h in r.history], "ctype": r.headers.get("content-type")})
    except Exception as e:
        index.append({"url": url, "file": name, "error": repr(e)})
    print(json.dumps(index[-1]))
    time.sleep(1.5)
(out / "index.json").write_text(json.dumps(index, indent=1))

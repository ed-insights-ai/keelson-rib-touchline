"""Temporary: fetch the Nuxt chunks a page loads and keep the API-looking strings."""
import re, pathlib, requests, time
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (Touchline educational/research collector)"
page = s.get("https://umterps.com/sports/womens-soccer/schedule", timeout=40).text
chunks = sorted(set(re.findall(r'"(/_nuxt/[^"]+\.js)"', page)))
out = []
for c in chunks:
    try:
        js = s.get("https://umterps.com" + c, timeout=40).text
    except Exception as e:
        out.append(f"{c} ERR {e!r}"); continue
    for m in re.finditer(r'.{0,160}(?:api/v[123]|/api/|scheduleId|pastSchedules|schedule_id).{0,200}', js):
        out.append(f"{c}: {m.group(0)}")
    time.sleep(0.3)
pathlib.Path(".probe/pages/chunks.txt").write_text("\n".join(out))
print(len(chunks), len(out))

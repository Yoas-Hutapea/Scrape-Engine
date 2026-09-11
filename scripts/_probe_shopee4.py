import re
import json
from pathlib import Path

html = Path("output/_shopee_html.html").read_text(encoding="utf-8")
for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
    data = json.loads(m.group(1))
    Path("output/_shopee_ldjson.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(type(data), list(data) if isinstance(data, dict) else len(data))
    print(json.dumps(data, ensure_ascii=False)[:1500])

import re
from pathlib import Path

s = Path("output/_script_3.js").read_text(encoding="utf-8")
# find keys on window
keys = re.findall(r"window\.([A-Za-z0-9_\$]+)\s*=", s)
print("window keys", sorted(set(keys))[:50], "count", len(set(keys)))

# find large JSON-like assignments
for m in re.finditer(r"(window\.[A-Za-z0-9_\$]+)\s*=\s*(\{|\[)", s):
    name = m.group(1)
    start = m.start(2)
    # score by nearby ROOT_QUERY
    snippet = s[start : start + 200]
    if "ROOT_QUERY" in s[start : start + 5000] or "pdpMainInfo" in s[start : start + 5000]:
        print("candidate", name, "at", start, snippet[:80].replace("\n", " "))

idx = s.find("ROOT_QUERY")
print("context before ROOT", repr(s[idx - 80 : idx + 40]))

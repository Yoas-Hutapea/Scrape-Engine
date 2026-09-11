import json
import re
from pathlib import Path


def extract_js_object(source: str, marker: str) -> dict | None:
    idx = source.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    while start < len(source) and source[start] in " \n\r\t":
        start += 1
    if start >= len(source) or source[start] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(source)):
        ch = source[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = source[start : i + 1]
                return json.loads(raw)
    return None


s = Path("output/_script_3.js").read_text(encoding="utf-8")
cache = extract_js_object(s, "window.__cache=")
print("cache keys", list(cache)[:5] if cache else None)
print("ROOT keys sample", list(cache["ROOT_QUERY"])[:10] if cache else None)

# Find pdpMainInfo entries
rq = cache["ROOT_QUERY"]
pdp_keys = [k for k in rq if "pdpMainInfo" in k]
print("pdp keys", len(pdp_keys))
print(pdp_keys[0][:120] if pdp_keys else None)

# Resolve references and find children
main = rq[pdp_keys[0]]
print("main type", type(main), list(main)[:20] if isinstance(main, dict) else main)

# Dump all typename counts
from collections import Counter

c = Counter()
for k, v in cache.items():
    if isinstance(v, dict) and "typename" in v:  # may be __typename
        c[v.get("__typename") or v.get("typename")] += 1
    elif isinstance(v, dict) and "__typename" in v:
        c[v["__typename"]] += 1
print(c.most_common(20))

# Find keys containing children product variants
child_like = [k for k, v in cache.items() if isinstance(v, dict) and "optionName" in v]
print("optionName entities", len(child_like))
if child_like:
    print(json.dumps(cache[child_like[0]], ensure_ascii=False)[:500])

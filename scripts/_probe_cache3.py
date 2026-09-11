import json
from pathlib import Path


def extract_js_object(source: str, marker: str):
    idx = source.find(marker)
    start = idx + len(marker)
    while source[start] in " \n\r\t":
        start += 1
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
                return json.loads(source[start : i + 1])
    return None


def resolve(cache, node, depth=0):
    if depth > 25 or node is None:
        return node
    if isinstance(node, dict):
        if node.get("type") == "id" and "id" in node:
            return resolve(cache, cache.get(node["id"]), depth + 1)
        return {k: resolve(cache, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(cache, x, depth + 1) for x in node]
    return node


s = Path("output/_script_3.js").read_text(encoding="utf-8")
cache = extract_js_object(s, "window.__cache=")

for tname in ("pdpDataProductVariant", "pdpProductVariantOutput", "pdpContentSnapshotVariant"):
    keys = [k for k, v in cache.items() if isinstance(v, dict) and v.get("__typename") == tname]
    print("====", tname, keys)
    if keys:
        print(json.dumps(resolve(cache, cache[keys[0]]), ensure_ascii=False)[:2000])

# child stock
children = [v for v in cache.values() if isinstance(v, dict) and v.get("__typename") == "pdpProductVariantChildren"]
c = resolve(cache, children[0])
print("stock keys", {k: c.get(k) for k in c if "stock" in k.lower() or k in ("price", "slashPriceFmt", "optionName")})
print("full stock", c.get("stock"))

# description elsewhere
for k, v in cache.items():
    if isinstance(v, dict) and isinstance(v.get("description"), str) and len(v["description"]) > 20:
        print("desc in", k, v["description"][:120])

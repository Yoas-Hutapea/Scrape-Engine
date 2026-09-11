import json
from pathlib import Path
from collections import defaultdict


def extract_js_object(source: str, marker: str):
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
                return json.loads(source[start : i + 1])
    return None


def resolve(cache, node, depth=0):
    if depth > 20 or node is None:
        return node
    if isinstance(node, dict):
        if set(node.keys()) >= {"type", "id"} and node.get("type") == "id":
            return resolve(cache, cache.get(node["id"]), depth + 1)
        return {k: resolve(cache, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(cache, x, depth + 1) for x in node]
    return node


s = Path("output/_script_3.js").read_text(encoding="utf-8")
cache = extract_js_object(s, "window.__cache=")

basic_keys = [k for k, v in cache.items() if isinstance(v, dict) and v.get("__typename") == "pdpBasicInfo"]
print("basic", basic_keys)
basic = cache[basic_keys[0]]
print(json.dumps({k: basic[k] for k in basic if k not in ("description",)}, ensure_ascii=False)[:1500])
print("desc len", len(basic.get("description") or ""))
print("weight", basic.get("weight"))

children = [v for v in cache.values() if isinstance(v, dict) and v.get("__typename") == "pdpProductVariantChildren"]
print("children", len(children))
c0 = resolve(cache, children[0])
print(json.dumps(c0, ensure_ascii=False)[:800])

# find variant component with options names
opts = [v for v in cache.values() if isinstance(v, dict) and v.get("__typename") == "pdpProductVariantOption"]
print("options typename count", len(opts))
print(json.dumps(resolve(cache, opts[0]), ensure_ascii=False)[:500])

# find parent variant widget
for k, v in cache.items():
    if isinstance(v, dict) and "children" in v and "options" in str(v)[:200]:
        pass

# search keys with Variant in typename
types = defaultdict(list)
for k, v in cache.items():
    if isinstance(v, dict) and v.get("__typename"):
        types[v["__typename"]].append(k)
for t in sorted(types):
    if "ariant" in t or "Basic" in t or "ContentProduct" in t:
        print(t, len(types[t]))

# content product detail
for k in types["pdpContentProductDetail"][:1]:
    print("content", json.dumps(resolve(cache, cache[k]), ensure_ascii=False)[:600])

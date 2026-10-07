import json
p = "/c/Users/Thabang/Desktop/ai bin/_tiktok_build_20261004/data/meta.json"
meta = json.load(open(p, encoding="utf-8"))
print("TYPE:", type(meta))
print("LEN:", len(meta))
print("RECORD KEYS:", list(meta[0].keys()))
print()
print("RECORD 0:", json.dumps(meta[0], indent=2, ensure_ascii=False))
print()
handles = [r.get("handle") for r in meta]
print("HANDLES:", handles)
for r in meta:
    h = r.get("handle", "")
    if h in ("hatsunama", "satriaabaharii", "marcinteodoru"):
        print("MATCH:", json.dumps(r, indent=2, ensure_ascii=False))

import os, json

f1 = r"h:\Repos\Personal\Softball\data\sharks\api_captures.json"
f2 = r"h:\Repos\Personal\Softball\data\sharks\app_plays_api.json"

print("api_captures.json:", "exists" if os.path.exists(f1) else "MISSING", os.path.getsize(f1) if os.path.exists(f1) else 0, "bytes")
print("app_plays_api.json:", "exists" if os.path.exists(f2) else "MISSING", os.path.getsize(f2) if os.path.exists(f2) else 0, "bytes")

if os.path.exists(f1):
    with open(f1, "r") as f:
        data = json.load(f)
    print(f"\napi_captures has {len(data)} captured responses:")
    for r in data:
        print(f"  {r['status']} {r['url'][:100]} ({r['size']:,} bytes)")

if os.path.exists(f2):
    with open(f2, "r") as f:
        body = f.read()
    print(f"\napp_plays_api.json preview ({len(body)} chars):")
    print(body[:500])

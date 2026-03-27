import json

DATA_FILE = "h:/Repos/Personal/Softball/data/sharks/raw_plays_network.json"

with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Loaded {len(data)} payloads.")

for i, p in enumerate(data):
    url = p.get('url', 'UNKNOWN')
    print(f"\n--- Payload {i} ---")
    print(f"URL: {url}")
    payload_data = p.get('data', {})
    
    if isinstance(payload_data, dict):
        keys = list(payload_data.keys())
        print(f"Keys: {keys}")
        
        # Check for deep keys that might represent plays
        for k in keys:
            if isinstance(payload_data[k], dict):
                print(f"  {k} object keys: {list(payload_data[k].keys())}")
            elif isinstance(payload_data[k], list):
                print(f"  {k} list length: {len(payload_data[k])}")
                if len(payload_data[k]) > 0 and isinstance(payload_data[k][0], dict):
                     print(f"  Example {k}[0] keys: {list(payload_data[k][0].keys())}")
    
    elif isinstance(payload_data, list):
        print(f"Root is a list of length {len(payload_data)}")
        if len(payload_data) > 0 and isinstance(payload_data[0], dict):
            print(f"  Example list item keys: {list(payload_data[0].keys())}")
            
    print("-" * 40)

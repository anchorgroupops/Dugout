import json

DATA_FILE = "h:/Repos/Personal/Softball/data/sharks/raw_plays_network.json"

with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

if len(data) > 2:
    p2_data = data[2].get('data', {})
    print("--- Payload 2 ---")
    if isinstance(p2_data, dict):
        keys = list(p2_data.keys())
        print(f"Keys: {keys}")
        
        # Let's see if plays exist
        if 'plays' in p2_data:
            plays = p2_data['plays']
            print(f"Found {len(plays)} plays!")
            if len(plays) > 0:
                print("Example play:")
                print(json.dumps(plays[0], indent=2))
        else:
             print("No 'plays' key found directly. Let's look deeper.")
             for k, v in p2_data.items():
                 if isinstance(v, list) and len(v) > 0:
                      print(f"  List key '{k}' length: {len(v)}")
                      print(f"  Example '{k}' item keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0])}")
    elif isinstance(p2_data, list):
         print(f"Payload 2 is a list of {len(p2_data)} items.")
         if len(p2_data) > 0:
              print(f"Example item: {json.dumps(p2_data[0])}")

else:
    print("Payload 2 doesn't exist.")

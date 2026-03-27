import json
from pathlib import Path

# Load the HAR file
HAR_FILE = Path("h:/Repos/Personal/Softball/data/sharks/game_network.har")

if not HAR_FILE.exists():
    print(f"File not found: {HAR_FILE}")
    exit(1)

with open(HAR_FILE, "r", encoding="utf-8") as f:
    har_data = json.load(f)

print(f"Loaded HAR file with {len(har_data['log']['entries'])} requests.")

# Look for responses that might contain play data
# Usually these have "plays", "events", or "game" in the URL and return JSON
found_plays = []

for entry in har_data["log"]["entries"]:
    request = entry["request"]
    response = entry["response"]
    url = request["url"]
    
    # Filter for API-like URLs
    if "api" in url.lower() or "graphql" in url.lower():
        mime_type = response["content"].get("mimeType", "").lower()
        if "application/json" in mime_type:
            # Check if the URL might be related to plays/events
            # Or if it's the main game fetch
            if "play" in url.lower() or "event" in url.lower() or "game" in url.lower():
                try:
                    text_content = response["content"].get("text", "")
                    if text_content:
                        json_payload = json.loads(text_content)
                        # Quick heuristic: does the JSON look like play/event data?
                        # Let's save the URL and a snippet of the JSON keys
                        
                        if isinstance(json_payload, dict):
                            keys = list(json_payload.keys())
                            if "plays" in keys or "events" in keys or "data" in keys:
                                found_plays.append({
                                    "url": url,
                                    "keys": keys,
                                    "snippet": str(json_payload)[:500] # First 500 chars
                                })
                        elif isinstance(json_payload, list):
                            if len(json_payload) > 0:
                                found_plays.append({
                                    "url": url,
                                    "type": "list",
                                    "length": len(json_payload),
                                    "snippet": str(json_payload)[:500]
                                })
                                
                except Exception as e:
                    pass

print(f"Found {len(found_plays)} potential PBP API responses:")
for item in found_plays:
    print(f"\n--- URL: {item['url']} ---")
    if "keys" in item: print(f"Keys: {item['keys']}")
    if "type" in item: print(f"Type: {item['type']} (Length: {item['length']})")
    print(f"Snippet: {item['snippet']}")

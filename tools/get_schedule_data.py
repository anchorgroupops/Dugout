import requests
import json
from bs4 import BeautifulSoup
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
AUTH_FILE = ROOT_DIR / "data" / "auth.json"

def run():
    with open(AUTH_FILE, "r") as f:
        auth = json.load(f)
    cookies = {cookie["name"]: cookie["value"] for cookie in auth["cookies"]}
    
    url = "https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule"
    print(f"Fetching schedule: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    resp = requests.get(url, cookies=cookies, headers=headers)
    if resp.status_code != 200:
        print("Failed to fetch schedule, status:", resp.status_code)
        return
        
    soup = BeautifulSoup(resp.text, 'html.parser')
    next_data = soup.find('script', id='__NEXT_DATA__')
    if not next_data:
        print("Could not find __NEXT_DATA__ script tag")
        return
        
    data = json.loads(next_data.string)
    
    # Write full JSON to inspect
    out_file = ROOT_DIR / "data" / "sharks" / "schedule_next_data.json"
    out_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(str(data))} bytes to {out_file}")

if __name__ == "__main__":
    run()

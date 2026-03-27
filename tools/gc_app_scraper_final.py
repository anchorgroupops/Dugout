import adbutils
import time
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

# Config
ADB_SERIAL = "127.0.0.1:5555"
DATA_DIR = Path(r"H:\Repos\Personal\Softball\data\sharks")
PLAYS_OUT = DATA_DIR / "plays.json"

def get_plays_from_xml(xml_content):
    try:
        root = ET.fromstring(xml_content)
    except:
        return []
        
    plays = []
    current_inning = "Unknown"
    
    # Find the recycler
    recycler = None
    for node in root.iter('node'):
        if node.get('resource-id') == "com.gc.teammanager:id/recycler_view":
            recycler = node
            break
            
    if recycler is None:
        return []

    for child in recycler:
        # Check if this child is a header
        if child.get('resource-id') == "com.gc.teammanager:id/header_text":
            current_inning = child.get('text')
            continue
            
        # Check if it's a play (usually a ViewGroup or FrameLayout)
        # We search inside it for the key fields
        headline = child.find(".//*[@resource-id='com.gc.teammanager:id/headline_text']")
        desc = child.find(".//*[@resource-id='com.gc.teammanager:id/description_text']")
        pitches = child.find(".//*[@resource-id='com.gc.teammanager:id/pitches_text']")
        extra = child.find(".//*[@resource-id='com.gc.teammanager:id/extra_header_text']")
        
        if headline is not None or desc is not None:
            play = {
                "inning": current_inning,
                "headline": headline.get('text') if headline is not None else "",
                "extra": extra.get('text') if extra is not None else "",
                "pitches": pitches.get('text') if pitches is not None else "",
                "description": desc.get('text') if desc is not None else ""
            }
            # Create a unique key to avoid duplicates when scrolling
            play["id"] = f"{play['inning']}|{play['headline']}|{play['description']}"
            plays.append(play)
            
    return plays

def main():
    print(f"[Scraper] Connecting to ADB {ADB_SERIAL}...")
    client = adbutils.AdbClient(host='127.0.0.1', port=5037)
    client.connect(ADB_SERIAL)
    d = client.device(serial=ADB_SERIAL)
    
    all_plays = {}
    
    print("[Scraper] Starting scroll-and-capture...")
    # We'll scroll up/down a few times to ensure we hit everything.
    # Since it's a baseball game, there might be 50-100 plays.
    
    for scroll in range(15): # 15 scrolls should cover a whole game
        print(f"  Capture {scroll+1}/15...")
        xml = d.dump_hierarchy()
        captured = get_plays_from_xml(xml)
        
        new_found = 0
        for p in captured:
            if p["id"] not in all_plays:
                all_plays[p["id"]] = p
                new_found += 1
        
        print(f"    Found {len(captured)} plays ({new_found} new).")
        
        # Scroll up (showing older/earlier plays)
        # Coordinates for scroll: swipe from top to bottom to scroll up the list
        d.shell("input swipe 500 400 500 1500 500") 
        time.sleep(1.5)
        
    # Convert back to list and sort by some logic? 
    # Actually, they are added in the order found (reverse chronological usually)
    final_list = list(all_plays.values())
    
    with open(PLAYS_OUT, 'w', encoding='utf-8') as f:
        json.dump(final_list, f, indent=2)
        
    print(f"\n[Scraper] SUCCESS! Extracted {len(final_list)} total unique plays to {PLAYS_OUT}")

if __name__ == "__main__":
    main()

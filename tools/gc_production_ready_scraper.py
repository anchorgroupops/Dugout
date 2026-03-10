import uiautomator2 as u2
import time
import json
import os
from pathlib import Path

# Config
ADB_SERIAL = "127.0.0.1:5555"
DATA_DIR = Path(r"H:\Repos\Personal\Softball\data\sharks")
OUT_FILE = DATA_DIR / "plays_production.json"

def get_visible_plays(d):
    plays = []
    current_inning = "Unknown"
    
    # We find all elements and manually find the structure
    # The structure is: 
    # Inning Header (id: header_text)
    # Play ViewGroup containing:
    #   headline_text
    #   pitches_text
    #   description_text
    #   extra_header_text
    
    # Iterating through all relevant fields
    visible_texts = []
    
    inn_nodes = d(resourceId="com.gc.teammanager:id/header_text")
    head_nodes = d(resourceId="com.gc.teammanager:id/headline_text")
    
    # We find the parents of the headlines to group them
    for head in head_nodes:
        # Get the play group (parent or grandparent)
        # Using u2.info which is faster
        info = head.info
        bounds = info['bounds']
        
        # Find associated fields by proximity (same horizontal range)
        play = {
            "headline": info['text'],
            "inning": "Unknown",
            "pitches": "",
            "description": "",
            "extra": ""
        }
        
        # Match inning (last inning header ABOVE this headline)
        for inn in inn_nodes:
            if inn.info['bounds']['bottom'] <= bounds['top']:
                play["inning"] = inn.info['text']
        
        # Find pitches and description in the same vertical block
        # We'll just look for any text in the same 'parent' ViewGroup
        parent = head.sibling(resourceId="com.gc.teammanager:id/pitches_text")
        if parent.exists: play["pitches"] = parent.info['text']
        
        desc = head.sibling(resourceId="com.gc.teammanager:id/description_text")
        if desc.exists: play["description"] = desc.info['text']
        
        ext = head.sibling(resourceId="com.gc.teammanager:id/extra_header_text")
        if ext.exists: play["extra"] = ext.info['text']
        
        # Unique ID for deduplication
        play["id"] = f"{play['inning']}|{play['headline']}|{play['description']}"
        plays.append(play)
        
    return plays

def main():
    print(f"[Production Scraper] Connecting to {ADB_SERIAL}...")
    d = u2.connect(ADB_SERIAL)
    
    if not d(text="Plays").exists:
        print("ERROR: 'Plays' tab not found. Please ensure the app is on the Plays screen.")
        return

    all_plays = {}
    print("[Production Scraper] Starting full game extraction...")
    
    # 1. Scroll to the TOP first (just in case)
    print("  Scrolling to top...")
    for _ in range(5):
        d.swipe_ext("down") # Scroll up
        time.sleep(1)
        
    # 2. Capture and scroll DOWN (swipe up)
    no_new_count = 0
    total_searches = 30 # Games shouldn't be longer than 30 full scrolls
    
    for i in range(total_searches):
        print(f"  Capture {i+1}... (Currently found {len(all_plays)} unique plays)")
        visible = get_visible_plays(d)
        
        new_this_step = 0
        for p in visible:
            if p["id"] not in all_plays:
                all_plays[p["id"]] = p
                new_this_step += 1
                
        if new_this_step == 0:
            no_new_count += 1
        else:
            no_new_count = 0
            
        if no_new_count >= 3:
            print("  No new plays found for 3 consecutive scrolls. Ending.")
            break
            
        # Scroll down (swipe UP)
        d.swipe_ext("up")
        time.sleep(1.5)
        
    final_list = list(all_plays.values())
    print(f"\n[Production Scraper] SUCCESS! Captured {len(final_list)} unique plays.")
    
    # Save results
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_list, f, indent=2)
    print(f"[Production Scraper] Data saved to {OUT_FILE}")

if __name__ == "__main__":
    main()

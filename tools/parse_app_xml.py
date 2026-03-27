import xml.etree.ElementTree as ET
import json
import os
from pathlib import Path

XML_FILE = r"H:\Repos\Personal\Softball\data\sharks\ui_dump.xml"
OUT_FILE = r"H:\Repos\Personal\Softball\data\sharks\plays.json"

def parse_gc_xml(xml_path):
    if not os.path.exists(xml_path):
        print(f"Error: {xml_path} not found.")
        return []

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        print(f"XML Parse Error: {e}")
        return []
        
    root = tree.getroot()
    plays = []
    
    # Each play is usually a ViewGroup containing specific resource-ids
    # We'll look for nodes that have children with the relevant IDs
    
    # First, find the recycler_view
    recycler = None
    for node in root.iter():
        if node.get('resource-id') == "com.gc.teammanager:id/recycler_view":
            recycler = node
            break
            
    if not recycler:
        print("Could not find the plays list (recycler_view) in the XML.")
        return []

    # Iterate through the children of the recycler
    # Children can be headers (innings) or play groups
    current_inning = "Unknown"
    
    for play_group in recycler:
        # Check if it's a header (Inning)
        header = play_group.find(".//*[@resource-id='com.gc.teammanager:id/header_text']")
        if header is not None:
            current_inning = header.get('text')
            continue
            
        # It's a play
        play_data = {
            "inning": current_inning,
            "headline": "",
            "extra_header": "",
            "pitches": "",
            "description": ""
        }
        
        # Headline
        node = play_group.find(".//*[@resource-id='com.gc.teammanager:id/headline_text']")
        if node is not None: play_data["headline"] = node.get('text')
        
        # Extra (Score/Outs)
        node = play_group.find(".//*[@resource-id='com.gc.teammanager:id/extra_header_text']")
        if node is not None: play_data["extra_header"] = node.get('text')
        
        # Pitches
        node = play_group.find(".//*[@resource-id='com.gc.teammanager:id/pitches_text']")
        if node is not None: play_data["pitches"] = node.get('text')
        
        # Description
        node = play_group.find(".//*[@resource-id='com.gc.teammanager:id/description_text']")
        if node is not None: play_data["description"] = node.get('text')
        
        # Only add if it has some content
        if play_data["headline"] or play_data["description"]:
            plays.append(play_data)
            
    return plays

def main():
    print(f"Parsing {XML_FILE}...")
    plays = parse_gc_xml(XML_FILE)
    
    if plays:
        with open(OUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(plays, f, indent=2)
        print(f"Successfully extracted {len(plays)} plays to {OUT_FILE}")
        # Print the first few for verification
        for p in plays[:3]:
            print(f" - [{p['inning']}] {p['headline']}: {p['description'][:60]}...")
    else:
        print("No plays found in the XML.")

if __name__ == "__main__":
    main()

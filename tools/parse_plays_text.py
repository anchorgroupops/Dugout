import os
import re
import json
from pathlib import Path

DATA_DIR = Path("h:/Repos/Personal/Softball/data/sharks")
TEXT_FILE = DATA_DIR / "raw_plays_text.txt"
OUT_FILE = DATA_DIR / "plays.json"

def parse_plays_text(filepath):
    if not filepath.exists():
        print(f"File not found: {filepath}")
        return
        
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    plays = []
    current_inning = ""
    current_team = ""
    
    # We'll use a state machine approach to process the flat text into structured plays
    # States: FIND_INNING, FIND_RESULT, FIND_OUTS, FIND_PITCHES, FIND_DESC
    
    # Start looking for the first inning marker
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        
        # Check if line is an Inning Header (e.g. "Top 7th - Peppers")
        inning_match = re.match(r"(Top|Bottom)\s+(\w+)\s+-\s+(.+)", line, re.IGNORECASE)
        if inning_match:
            current_inning = f"{inning_match.group(1)} {inning_match.group(2)}"
            current_team = inning_match.group(3)
            idx += 1
            continue
            
        # If we have an inning, the next lines usually follow a 4-line block:
        # 1. Result (e.g. "Strikeout", "Single", "Home Run")
        # 2. X Outs (e.g. "3 Outs", "1 Out")
        # 3. Pitches (e.g. "Strike 1 looking, Ball 1, In Play.")
        # 4. Description (e.g. "A DiCenzo strikes out swinging, V Cagle pitching.")
        
        if current_inning and idx + 3 < len(lines):
            # Let's peek to see if the second line is an 'Outs' indicator
            outs_match = re.match(r"(\d)\s+Outs?", lines[idx+1], re.IGNORECASE)
            
            if outs_match:
                result = lines[idx]
                outs = int(outs_match.group(1))
                pitches = lines[idx+2]
                description = lines[idx+3]
                
                # Check for "Lineup changed:" in the pitches line to clean it up
                lineup_change = None
                if "Lineup changed:" in pitches:
                    parts = pitches.split(", ", 1) # Split after the lineup change string
                    lineup_change = parts[0]
                    pitches = parts[1] if len(parts) > 1 else ""

                play_obj = {
                    "inning": current_inning,
                    "team": current_team,
                    "result": result,
                    "outs": outs,
                    "pitches": pitches,
                    "description": description
                }
                if lineup_change:
                    play_obj["lineup_change"] = lineup_change
                    
                plays.append(play_obj)
                
                # Skip past these 4 lines
                idx += 4
                continue
                
        # If it doesn't match the 4-line pattern, just step forward
        idx += 1
        
    print(f"Parsed {len(plays)} structured plays.")
    
    with open(OUT_FILE, "w", encoding="utf-8") as f:
         json.dump(plays, f, indent=4)
         
    print(f"Saved structured plays to {OUT_FILE}")

if __name__ == "__main__":
    parse_plays_text(TEXT_FILE)

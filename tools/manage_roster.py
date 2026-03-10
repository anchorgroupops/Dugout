"""
Manage Sharks Roster Availability
CLI tool to toggle player availability for the next game.
"""
import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
TEAM_FILE = SHARKS_DIR / "team.json"
AVAILABILITY_FILE = SHARKS_DIR / "availability.json"

def load_team():
    if not TEAM_FILE.exists():
        print(f"Error: {TEAM_FILE} not found. Run scraper first.")
        return None
    with open(TEAM_FILE, "r") as f:
        return json.load(f)

def load_availability():
    if not AVAILABILITY_FILE.exists():
        return {}
    with open(AVAILABILITY_FILE, "r") as f:
        return json.load(f)

def save_availability(data):
    with open(AVAILABILITY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def list_players(team_data, availability):
    players = team_data.get("roster", [])
    print(f"\n{'#' : <3} | {'Name' : <25} | {'Active' : <6} | {'Core' : <4}")
    print("-" * 50)
    for i, p in enumerate(players):
        name = f"{p.get('first', '')} {p.get('last', '')}".strip()
        is_core = p.get('core', False)
        # Use player name or some unique ID as key. Team.json doesn't have explicit IDs but has names/numbers.
        # Roster manifest uses full names.
        status = availability.get(name, True) # Default to True
        print(f"{i+1 : <3} | {name : <25} | {'[X]' if status else '[ ]'}    | {'*' if is_core else ''}")

def toggle_player(team_data, availability, index):
    players = team_data.get("roster", [])
    if 0 < index <= len(players):
        p = players[index-1]
        name = f"{p.get('first', '')} {p.get('last', '')}".strip()
        current_status = availability.get(name, True)
        availability[name] = not current_status
        print(f"Toggled {name} to {'Active' if not current_status else 'Inactive'}.")
        return True
    else:
        print("Invalid index.")
        return False

def main():
    team_data = load_team()
    if not team_data:
        return

    availability = load_availability()

    if len(sys.argv) > 1:
        # Command line mode for automation/scripts
        cmd = sys.argv[1]
        if cmd == "list":
            list_players(team_data, availability)
        elif cmd == "toggle" and len(sys.argv) > 2:
            try:
                idx = int(sys.argv[2])
                if toggle_player(team_data, availability, idx):
                    save_availability(availability)
            except ValueError:
                print("Index must be an integer.")
        elif cmd == "set-all" and len(sys.argv) > 2:
            state = sys.argv[2].lower() == "true"
            for p in team_data.get("roster", []):
                name = f"{p.get('first', '')} {p.get('last', '')}".strip()
                availability[name] = state
            save_availability(availability)
            print(f"All players set to {'Active' if state else 'Inactive'}.")
        return

    # Interactive mode
    while True:
        list_players(team_data, availability)
        print("\nCommands: <index> to toggle, 'a' for all active, 'n' for none, 'q' to quit")
        choice = input("> ").strip().lower()
        
        if choice == 'q':
            break
        elif choice == 'a':
            for p in team_data.get("roster", []):
                name = f"{p.get('first', '')} {p.get('last', '')}".strip()
                availability[name] = True
            save_availability(availability)
        elif choice == 'n':
            for p in team_data.get("roster", []):
                name = f"{p.get('first', '')} {p.get('last', '')}".strip()
                availability[name] = False
            save_availability(availability)
        else:
            try:
                idx = int(choice)
                if toggle_player(team_data, availability, idx):
                    save_availability(availability)
            except ValueError:
                print("Unknown command.")

if __name__ == "__main__":
    main()

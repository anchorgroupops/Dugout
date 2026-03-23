import json
from pathlib import Path
from gc_scraper import GameChangerScraper

# We'll mock the upload for now since NotebookLM MCP requires specific interactions
# The system constitution specifies manual upload is an acceptable fallback

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"

def prepare_notebooklm_payload():
    """Compiles all JSON data into a single Markdown document for NotebookLM ingestion."""
    markdown_content = "# Sharks Softball Season Data\n\n"
    
    # 1. Roster & Stats
    team_file = SHARKS_DIR / "team.json"
    if team_file.exists():
        with open(team_file) as f:
            team_data = json.load(f)
            markdown_content += f"## Roster & Stats\n\n"
            for player in team_data.get("roster", []):
                markdown_content += f"### {player.get('number', '')} {player.get('name', 'Unknown')}\n"
                markdown_content += f"- Runs: {player.get('runs', 0)}\n"
                markdown_content += f"- Hits: {player.get('hits', 0)}\n"
                markdown_content += f"- RBI: {player.get('rbi', 0)}\n"
                markdown_content += f"- Avg: {player.get('avg', '.000')}\n\n"

    # 2. Schedule
    schedule_file = SHARKS_DIR / "schedule.json"
    if schedule_file.exists():
         with open(schedule_file) as f:
             schedule_data = json.load(f)
             markdown_content += "## Schedule Overview\n\n"
             markdown_content += schedule_data.get("raw_content", "No schedule scraped yet.")
             markdown_content += "\n\n"

    # Write output payload
    payload_file = DATA_DIR / "notebooklm_payload.md"
    with open(payload_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)
        
    print(f"[NotebookLM] Prepared data payload at {payload_file}")
    print("[NotebookLM] Since direct API uploads are restricted, please manually drag-and-drop 'notebooklm_payload.md' into your NotebookLM 'PCLL 🥎' notebook.")
    
if __name__ == "__main__":
    prepare_notebooklm_payload()

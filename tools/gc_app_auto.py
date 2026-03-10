import uiautomator2 as u2
import time
from pathlib import Path

ADB_SERIAL = "127.0.0.1:5555"
DATA_DIR = Path(__file__).parent.parent / "data" / "sharks"

def main():
    print(f"[GC App] Connecting to {ADB_SERIAL}...")
    d = u2.connect(ADB_SERIAL)
    
    print("[GC App] Scanning screen for elements...")
    for elem in d(textMatches=".+"):
        txt = elem.info.get('text')
        if txt:
            print(f"  - {txt}")
            
    print("[GC App] Clicking 'Plays' tab...")
    if d(text="Plays").exists:
        d(text="Plays").click()
        print("[GC App] Clicked Plays. Waiting 3 seconds for data to load...")
        time.sleep(3)
    else:
        print("[GC App] 'Plays' text not found on screen!")
        return
        
    print("[GC App] Dumping Plays screen XML...")
    xml_content = d.dump_hierarchy()
    
    out_file = DATA_DIR / "app_plays_dump.xml"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"[GC App] Dumped Plays screen to {out_file}")

if __name__ == "__main__":
    main()

import uiautomator2 as u2
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# --- Configuration ---
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"

# ADB connection string. Adjust this if BlueStacks uses a different port.
# 127.0.0.1:5555 is common, or sometimes 62001 (Nox), 21503 (MEMu)
ADB_SERIAL = "127.0.0.1:5555" 

def connect_device():
    print(f"[GC App] Attempting to connect to Android emulator at {ADB_SERIAL}...")
    try:
        d = u2.connect(ADB_SERIAL)
        print(f"[GC App] Successfully connected! Device info: {d.info}")
        return d
    except Exception as e:
        print(f"[ERROR] Failed to connect to emulator. Is BlueStacks/ADB running? {e}")
        return None

def dump_screen_xml(d):
    """Dumps the current screen's UI hierarchy to an XML file for analysis."""
    print("[GC App] Dumping screen XML hierarchy...")
    xml_content = d.dump_hierarchy()
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_file = DATA_DIR / "app_screen_dump.xml"
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(xml_content)
        
    print(f"[GC App] Successfully dumped screen to {out_file}")
    
    # Let's count how many text nodes we found just for validation
    try:
        root = ET.fromstring(xml_content)
        text_nodes = [node.attrib.get('text') for node in root.iter('node') if node.attrib.get('text')]
        print(f"[GC App] Found {len(text_nodes)} text elements on screen.")
        if text_nodes:
            print("Sample text elements:")
            for t in text_nodes[:10]:
                print(f"  - {t}")
    except Exception as e:
         print(f"[GC App] Failed to parse XML: {e}")

def main():
    if len(sys.argv) > 1:
        global ADB_SERIAL
        ADB_SERIAL = sys.argv[1]
        
    d = connect_device()
    if not d:
        return
        
    # Example commands to interact (commented out until we confirm connection)
    # print("[GC App] Launching GameChanger...")
    # d.app_start("com.gamechanger.gcplaysports") 
    
    dump_screen_xml(d)

if __name__ == "__main__":
    main()

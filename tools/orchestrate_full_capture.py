"""
GameChanger API Capture - Full Orchestrator
Root ADB, start Frida + mitmdump, then trigger Plays/Scorebook to capture.
"""
import os
import subprocess
import threading
import time
from pathlib import Path

import adbutils
import frida
import uiautomator2 as u2

# Config
ADB_SERIAL = os.getenv("GC_ADB_SERIAL", "127.0.0.1:5555")
MITMDUMP = os.getenv(
    "GC_MITMDUMP",
    r"C:\Users\joely\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts\mitmdump.exe",
)
MITM_SCRIPT = os.getenv("GC_MITM_SCRIPT", r"H:\Repos\Personal\Softball\tools\capture_gc_api.py")
FRIDA_JS = os.getenv("GC_FRIDA_JS", r"H:\Repos\Personal\Softball\tools\disable_ssl_gc.js")
APP_PACKAGE = os.getenv("GC_APP_PACKAGE", "com.gc.teammanager")

PROXY_PORT = os.getenv("GC_PROXY_PORT", "54321")
PROXY_HOST = os.getenv("GC_PROXY_HOST", "10.0.2.2")

DATA_DIR = Path(r"H:\Repos\Personal\Softball\data\sharks")
EVENTS_FILE = DATA_DIR / "app_plays_api.json"
SCOREBOOK_FILE = DATA_DIR / "scorebook_latest.pdf"
MITM_LOG = DATA_DIR / "mitm_log.txt"

# UI fallback coordinates (if resource-id click fails)
BOX_SCORE_TAP = (780, 261)
PLAYS_TAP = (540, 261)

mitm_proc = None
log_file = None
adb_device = None

def setup_root_adb():
    print("[Step 1] Attempting ADB root transition...")
    client = adbutils.AdbClient(host="127.0.0.1", port=5037)
    client.connect(ADB_SERIAL)
    d = client.device(serial=ADB_SERIAL)

    uid = d.shell("id")
    if "uid=0" in uid:
        print("[Step 1] Already root.")
    else:
        print("[Step 1] Calling adb root...")
        d.root()
        time.sleep(10)
        client.connect(ADB_SERIAL)
        d = client.device(serial=ADB_SERIAL)
        print(f"[Step 1] ID after root: {d.shell('id').strip()}")

    # Ensure frida port forwarding (helpful for BlueStacks)
    try:
        client.forward(ADB_SERIAL, "tcp:27042", "tcp:27042")
    except Exception as e:
        print(f"[Step 1] Warning: Port forward failed: {e}")

    # Set proxy for mitm
    d.shell(f"settings put global http_proxy {PROXY_HOST}:{PROXY_PORT}")
    return d

def run_frida_forever(d):
    print("[Frida] Starting server in foreground...")
    try:
        d.shell("/data/local/tmp/frida-server -l 0.0.0.0", timeout=3600)
    except Exception as e:
        print(f"[Frida] Server thread ended: {e}")

def get_frida_device():
    try:
        return frida.get_usb_device(timeout=5)
    except Exception:
        pass
    try:
        mgr = frida.get_device_manager()
        return mgr.add_remote_device("127.0.0.1:27042")
    except Exception as e:
        raise RuntimeError(f"Unable to acquire Frida device: {e}")

def trigger_ui():
    print("[Step 4] Triggering UI actions...")
    d = u2.connect(ADB_SERIAL)

    # Prefer resource-id clicks for stability
    if d(text="Plays").exists:
        d(text="Plays").click()
        time.sleep(2)
    else:
        adb_device.shell(f"input tap {PLAYS_TAP[0]} {PLAYS_TAP[1]}")
        time.sleep(2)

    # Scorebook button lives inside Plays list
    if d(resourceId="com.gc.teammanager:id/scorebook_button").exists:
        d(resourceId="com.gc.teammanager:id/scorebook_button").click()
        time.sleep(4)
    elif d(text="Scorebook").exists:
        d(text="Scorebook").click()
        time.sleep(4)
    else:
        # Fallback: try Box Score tab to force data refresh
        adb_device.shell(f"input tap {BOX_SCORE_TAP[0]} {BOX_SCORE_TAP[1]}")
        time.sleep(2)

def main():
    global mitm_proc, log_file, adb_device
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for f in [EVENTS_FILE, SCOREBOOK_FILE]:
            if f.exists():
                f.unlink()

        adb_device = setup_root_adb()

        # Start Frida in background thread
        frida_thread = threading.Thread(target=run_frida_forever, args=(adb_device,), daemon=True)
        frida_thread.start()
        time.sleep(5)

        # Start MITM
        print("[Step 2] Starting mitmdump...")
        log_file = open(MITM_LOG, "w")
        mitm_proc = subprocess.Popen(
            [MITMDUMP, "-p", str(PROXY_PORT), "-s", MITM_SCRIPT],
            stdout=log_file, stderr=subprocess.STDOUT
        )
        time.sleep(5)

        # Attach Frida
        print("[Step 3] Attaching Frida...")
        device = get_frida_device()
        with open(FRIDA_JS, "r", encoding="utf-8") as f:
            js_code = f.read()

        session = None
        for attempt in range(10):
            try:
                procs = device.enumerate_processes()
                gc_proc = [p for p in procs if APP_PACKAGE in p.name.lower()]
                if gc_proc:
                    print(f"[Step 3] Found GameChanger (PID {gc_proc[0].pid}). Attaching...")
                    session = device.attach(gc_proc[0].pid)
                    break
            except Exception as e:
                print(f"[Step 3] Attempt {attempt+1} failed: {e}")
            time.sleep(3)

        if not session:
            raise RuntimeError("Frida could not attach to GameChanger.")

        script = session.create_script(js_code)
        script.on("message", lambda msg, data: print(f"[Frida Debug] {msg}"))
        script.load()
        print("[Step 3] SSL bypass active.")

        # Trigger UI
        trigger_ui()

        print("\n*** MONITORING FOR DATA ***")
        for i in range(60, 0, -1):
            events_ok = EVENTS_FILE.exists() and EVENTS_FILE.stat().st_size > 100
            scorebook_ok = SCOREBOOK_FILE.exists() and SCOREBOOK_FILE.stat().st_size > 1000
            if events_ok or scorebook_ok:
                print("\n*** SUCCESS! Captured payloads ***")
                if events_ok:
                    print(f"  Events JSON: {EVENTS_FILE} ({EVENTS_FILE.stat().st_size} bytes)")
                if scorebook_ok:
                    print(f"  Scorebook PDF: {SCOREBOOK_FILE} ({SCOREBOOK_FILE.stat().st_size} bytes)")
                break
            if i % 10 == 0:
                print(f"  {i}s remaining...")
            time.sleep(1)

        if not EVENTS_FILE.exists() and not SCOREBOOK_FILE.exists():
            print("\n*** FAILED: No data captured. ***")

        script.unload()
        session.detach()

    except Exception as e:
        print(f"\n*** FATAL: {e} ***")
    finally:
        print("[Cleanup] Stopping services...")
        if adb_device:
            adb_device.shell("settings put global http_proxy :0")
            adb_device.shell("pkill frida-server")
        if mitm_proc:
            mitm_proc.terminate()
        if log_file:
            log_file.close()

if __name__ == "__main__":
    main()

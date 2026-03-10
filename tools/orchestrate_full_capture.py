"""
GameChanger API Capture - Root Transition Edition
Forces ADB root and verifies UID before capture.
"""
import subprocess
import time
import os
import adbutils
import frida
import threading

# Config
ADB_SERIAL = "127.0.0.1:5555"
MITMDUMP = r"C:\Users\joely\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts\mitmdump.exe"
MITM_SCRIPT = r"H:\Repos\Personal\Softball\tools\capture_gc_api.py"
FRIDA_JS = r"H:\Repos\Personal\Softball\tools\disable_ssl_gc.js"
APP_PACKAGE = "com.gc.teammanager"
PROXY_PORT = "54321" 
OUTPUT_FILE = r"H:\Repos\Personal\Softball\data\sharks\app_plays_api.json"
MITM_LOG = r"H:\Repos\Personal\Softball\data\sharks\mitm_log.txt"

# UI Coordinates
BOX_SCORE_TAP = (780, 261)
PLAYS_TAP = (540, 261)

mitm_proc = None
log_file = None
d = None

def setup_root_adb():
    print("[Step 1] Attempting ADB root transition...")
    client = adbutils.AdbClient(host='127.0.0.1', port=5037)
    client.connect(ADB_SERIAL)
    d = client.device(serial=ADB_SERIAL)
    
    # Check if already root
    uid = d.shell("id")
    if "uid=0" in uid:
        print("[Step 1] Already root.")
        return d
        
    print("[Step 1] Calling adb root...")
    d.root()
    time.sleep(10) # Wait for restart
    
    # Reconnect
    client.connect(ADB_SERIAL)
    d = client.device(serial=ADB_SERIAL)
    print(f"[Step 1] ID after root: {d.shell('id').strip()}")
    
    # Set proxy
    d.shell(f"settings put global http_proxy 10.0.2.2:{PROXY_PORT}")
    return d

def run_frida_forever(d):
    print("[Frida] Starting server in foreground...")
    try:
        # If we have root, we don't even need su -c
        d.shell("/data/local/tmp/frida-server -l 0.0.0.0", timeout=3600)
    except Exception as e:
        print(f"[Frida] Server thread ended: {e}")

def main():
    global mitm_proc, log_file, d
    try:
        if os.path.exists(OUTPUT_FILE):
             os.remove(OUTPUT_FILE)
             
        d = setup_root_adb()
        
        # Start Frida in background thread
        frida_thread = threading.Thread(target=run_frida_forever, args=(d,), daemon=True)
        frida_thread.start()
        time.sleep(5)
        
        # Start MITM
        print("[Step 2] Starting mitmdump...")
        log_file = open(MITM_LOG, "w")
        mitm_proc = subprocess.Popen(
            [MITMDUMP, "-p", PROXY_PORT, "-s", MITM_SCRIPT],
            stdout=log_file, stderr=subprocess.STDOUT
        )
        time.sleep(5)
        
        # Attach Frida
        print("[Step 3] Attaching Frida...")
        device = frida.get_usb_device(timeout=10)
        with open(FRIDA_JS, 'r') as f:
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
            raise Exception("Frida could not attach.")
            
        script = session.create_script(js_code)
        script.on('message', lambda msg, data: print(f"[Frida Debug] {msg}"))
        script.load()
        print("[Step 3] SSL bypass active.")

        # Trigger UI
        print("[Step 4] Triggering UI taps...")
        d.shell(f"input tap {BOX_SCORE_TAP[0]} {BOX_SCORE_TAP[1]}")
        time.sleep(3)
        d.shell(f"input tap {PLAYS_TAP[0]} {PLAYS_TAP[1]}")
        time.sleep(5)
        
        print("\n*** MONITORING FOR DATA ***")
        for i in range(40, 0, -1):
            if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 100:
                print(f"\n*** SUCCESS! Captured payload ({os.path.getsize(OUTPUT_FILE)} bytes) ***")
                break
            if i % 10 == 0:
                print(f"  {i}s remaining...")
            time.sleep(1)
            
        if not os.path.exists(OUTPUT_FILE):
            print("\n*** FAILED: No data captured. ***")
            
        script.unload()
        session.detach()
        
    except Exception as e:
        print(f"\n*** FATAL: {e} ***")
    finally:
        print("[Cleanup] Stopping services...")
        if d:
            d.shell("settings put global http_proxy :0")
            d.shell("pkill frida-server")
        if mitm_proc:
            mitm_proc.terminate()
        if log_file:
            log_file.close()

if __name__ == "__main__":
    main()

import subprocess
import uiautomator2 as u2
import time
import os

print("[Auto API] Starting MITM proxy listener...")
mitm_path = r"C:\Users\joely\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts\mitmdump.exe"
p = subprocess.Popen([mitm_path, "-s", r"h:\Repos\Personal\Softball\tools\capture_gc_api.py"])

time.sleep(2) # Give proxy time to bind to port 8080

print("[Auto API] Connecting to BlueStacks...")
d = u2.connect("127.0.0.1:5555")

print("[Auto API] Forcing a data refresh in GameChanger...")
if d(text="Box Score").exists:
    d(text="Box Score").click()
    print("[Auto API] Clicked Box Score. Waiting 2 seconds...")
    time.sleep(2)

if d(text="Plays").exists:
    print("[Auto API] Clicking Plays to trigger API payload...")
    d(text="Plays").click()
    print("[Auto API] Waiting for MITM to capture payload...")
    
# Wait up to 10 seconds for mitmdump to shut itself down (success)
try:
    p.wait(timeout=10)
    print("\n[Auto API] Success! Mitmproxy automatically shut down.")
except subprocess.TimeoutExpired:
    print("\n[Auto API] Timeout! Mitmproxy didn't capture the payload within 10 seconds.")
    p.terminate()

# Clean up android proxy setting so it doesn't break user internet
import adbutils
c = adbutils.AdbClient(host='127.0.0.1', port=5037)
dev = c.device(serial='127.0.0.1:5555')
print("[Auto API] Restoring Android proxy settings to none...")
dev.shell(['settings', 'put', 'global', 'http_proxy', ':0'])

if os.path.exists(r"h:\Repos\Personal\Softball\data\sharks\app_plays_api.json"):
    print("[Auto API] Verified app_plays_api.json exists!")
else:
    print("[Auto API] ERROR: app_plays_api.json was NOT saved.")

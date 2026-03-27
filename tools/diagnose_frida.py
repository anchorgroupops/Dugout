import adbutils
import time

d = adbutils.AdbClient(host='127.0.0.1', port=5037).device(serial='127.0.0.1:5555')

# Check if su is available
print("Checking su...")
su_check = d.shell("which su")
print("which su:", repr(su_check.strip()))

# Check whoami
print("whoami:", d.shell("whoami").strip())
print("id:", d.shell("id").strip())

# Try running frida-server directly as shell (works on some emulators)
print("\nAttempting frida-server as shell user (foreground test, 3 sec)...")
import subprocess
import threading

def run_frida_fg():
    try:
        result = d.shell("/data/local/tmp/frida-server", timeout=5)
        print("frida output:", result)
    except Exception as e:
        print("frida result:", type(e).__name__, str(e)[:200])

t = threading.Thread(target=run_frida_fg, daemon=True)
t.start()
time.sleep(3)

# Check if it's running now
ps = d.shell("ps | grep frida")
print("frida ps:", repr(ps.strip()))

# Also check if Frida Python can enumerate processes 
print("\nTesting Frida Python connection...")
try:
    import frida
    device = frida.get_usb_device(timeout=5)
    print("Frida device:", device)
    procs = device.enumerate_processes()
    print(f"Found {len(procs)} processes")
    gc_procs = [p for p in procs if 'gc' in p.name.lower() or 'teammanager' in p.name.lower()]
    print("GameChanger procs:", gc_procs)
except Exception as e:
    print("Frida error:", e)

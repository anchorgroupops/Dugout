import adbutils
import time
import os

def setup_adb():
    client = adbutils.AdbClient(host='127.0.0.1', port=5037)
    # Ensure connection
    addr = "127.0.0.1:5555"
    print(f"Connecting to {addr}...")
    try:
        client.connect(addr)
    except:
        pass
        
    d = client.device(serial=addr)
    print(f"Connected to {d.serial} (State: {d.get_state()})")
    
    # Port Forward for Frida
    print("Forwarding Frida port 27042...")
    # adbutils doesn't have a direct forward() on device object in some versions? 
    # Let's use the low-level client
    client.forward(addr, "tcp:27042", "tcp:27042")
    
    # Start Frida
    print("Restarting Frida server with 0.0.0.0 binding...")
    d.shell("su -c 'killall frida-server'")
    # Some frida-servers on android need -l 0.0.0.0 to be reachable from host even via adb forward
    d.shell("su -c '/data/local/tmp/frida-server -l 0.0.0.0 > /data/local/tmp/frida.log 2>&1 &'")
    time.sleep(3)
    
    # Verify Frida
    ps = d.shell("ps -A | grep frida")
    print(f"Frida PS: {ps.strip()}")
    log = d.shell("cat /data/local/tmp/frida.log")
    print(f"Frida Log: {log.strip()}")
    net = d.shell("netstat -antp | grep 27042")
    print(f"Frida Network: {net.strip()}")

if __name__ == "__main__":
    setup_adb()

import adbutils
import time

def find_bluestacks():
    client = adbutils.AdbClient(host='127.0.0.1', port=5037)
    
    # Try common ports
    for port in range(5555, 5565):
        addr = f"127.0.0.1:{port}"
        print(f"Checking {addr}...")
        try:
            client.connect(addr)
        except:
            pass
            
    devices = client.list()
    if not devices:
        print("No devices found via ADB.")
        return None
    
    for d in devices:
        print(f"Found: {d.serial} ({d.get_state()})")
        return d.serial
    return None

if __name__ == "__main__":
    find_bluestacks()

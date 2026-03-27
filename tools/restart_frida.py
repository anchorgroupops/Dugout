import adbutils
import time

d = adbutils.AdbClient(host='127.0.0.1', port=5037).device(serial='127.0.0.1:5555')

# Check if frida is already running
out = d.shell('ps | grep frida')
print('Before:', repr(out.strip()))

# Start frida-server as a daemon
d.shell('su -c "/data/local/tmp/frida-server -D"')
time.sleep(3)

out2 = d.shell('ps | grep frida')
print('After:', repr(out2.strip()))

import urllib.request
import lzma
import os
import adbutils
import time
import subprocess

url = 'https://github.com/frida/frida/releases/download/17.7.3/frida-server-17.7.3-android-x86_64.xz'
xz_path = r'h:\Repos\Personal\Softball\tools\frida-server.xz'
bin_path = r'h:\Repos\Personal\Softball\tools\frida-server'

print('Downloading frida-server...')
urllib.request.urlretrieve(url, xz_path)

print('Extracting...')
with lzma.open(xz_path, 'rb') as f_in:
    with open(bin_path, 'wb') as f_out:
        f_out.write(f_in.read())

c = adbutils.AdbClient(host='127.0.0.1', port=5037)
d = c.device(serial='127.0.0.1:5555')
d.root()
time.sleep(1)

print('Pushing to emulator...')
d.sync.push(bin_path, '/data/local/tmp/frida-server')

print('Setting permissions...')
d.shell(['chmod', '755', '/data/local/tmp/frida-server'])

print('Running frida-server in background...')
# run in background using sh
d.shell("su -c '/data/local/tmp/frida-server >/dev/null 2>&1 &'")
print('Frida Server started on BlueStacks!')

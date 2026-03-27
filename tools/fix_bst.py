import os

conf_path = r'C:\ProgramData\BlueStacks_nxt\bluestacks.conf'
if os.path.exists(conf_path):
    with open(conf_path, 'r', encoding='utf8') as f:
        c = f.read()

    # Enable ADB
    c = c.replace('bst.enable_adb_access="0"', 'bst.enable_adb_access="1"')
    
    with open(conf_path, 'w', encoding='utf8') as f:
        f.write(c)
    print("Config injected: ADB Enabled.")
else:
    print("Config not found.")

import os
conf_path = r'C:\ProgramData\BlueStacks_nxt\bluestacks.conf'
if os.path.exists(conf_path):
    with open(conf_path, 'r', encoding='utf8') as f:
        c = f.read()

    c = c.replace('bst.feature.rooting="0"', 'bst.feature.rooting="1"')
    c = c.replace('bst.instance.Pie64.enable_root_access="0"', 'bst.instance.Pie64.enable_root_access="1"')
    
    with open(conf_path, 'w', encoding='utf8') as f:
        f.write(c)
    print("Config injected: Root Enabled.")
else:
    print("Config not found.")

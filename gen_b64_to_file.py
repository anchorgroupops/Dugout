import base64
with open('H:\\Repos\\NotebookLM Librarian\\setup_pi.sh', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
with open('H:\\Repos\\NotebookLM Librarian\\setup_pi.b64', 'w') as f:
    f.write(b64)

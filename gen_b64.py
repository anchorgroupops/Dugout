import base64
with open('H:\\Repos\\NotebookLM Librarian\\setup_pi.sh', 'rb') as f:
    print(base64.b64encode(f.read()).decode())

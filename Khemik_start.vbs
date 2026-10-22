Set WshShell = CreateObject("WScript.Shell")
projectPath = "C:\Users\USUARIO\Desktop\inventario khemik pyton"
WshShell.Run "cmd /c ""cd /d """ & projectPath & """ && call .venv\Scripts\activate && python -m backend.app""", 0, False

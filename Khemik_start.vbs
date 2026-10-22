Set WshShell = CreateObject("WScript.Shell")
Set FileSystem = CreateObject("Scripting.FileSystemObject")
projectPath = FileSystem.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "cmd /c ""cd /d """ & projectPath & """ && call .venv\Scripts\activate.bat && python app.py""", 0, False

Set WshShell = CreateObject("WScript.Shell")
Set FileSystem = CreateObject("Scripting.FileSystemObject")
projectPath = FileSystem.GetParentFolderName(WScript.ScriptFullName)
batchPath = projectPath & "\Khemik.bat"
command = "cmd.exe /d /c ""call " & Chr(34) & batchPath & Chr(34) & """"

WshShell.Run command, 0, False
WScript.Sleep 2500
WshShell.Run "http://127.0.0.1:5000", 1, False

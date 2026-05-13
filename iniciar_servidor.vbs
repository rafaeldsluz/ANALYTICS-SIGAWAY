Set shell = CreateObject("WScript.Shell")
proj = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = proj
shell.Run "pythonw web_main.py", 0, False

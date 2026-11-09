' Neo Suggest on Windows: hidden, single-instance, restart-on-exit.
' Runs service\neo_suggest.py from the checkout this file lives in, against the
' local Magpie. Settings mirror deploy/install.sh; override via NEO_* user env vars.
Option Explicit
Dim sh, fso, wmi, procs, p, count, ownPath, root, py, env, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
ownPath = LCase(WScript.ScriptFullName)
count = 0
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='wscript.exe'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(LCase(p.CommandLine), ownPath) > 0 Then count = count + 1
  End If
Next
If count > 1 Then WScript.Quit 0

root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Python\bin\pythonw.exe")
If Not fso.FileExists(py) Then py = "pyw.exe"

Set env = sh.Environment("PROCESS")
If env("NEO_BIND") = "" Then env("NEO_BIND") = "127.0.0.1:3460"
If env("NEO_UPSTREAM") = "" Then env("NEO_UPSTREAM") = "http://127.0.0.1:3425/v1"

cmd = """" & py & """ -I """ & root & "\service\neo_suggest.py"""
Do
  sh.Run cmd, 0, True
  WScript.Sleep 10000
Loop

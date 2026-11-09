' Hidden, reconnecting loopback-only tunnel for Neo Composer.
Option Explicit
Dim sh, wmi, procs, p, count, ownPath, ssh
Set sh = CreateObject("WScript.Shell")
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
ssh = "C:\Windows\System32\OpenSSH\ssh.exe -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15 -o BatchMode=yes -L 127.0.0.1:3460:127.0.0.1:3460 ga401"
Do
  sh.Run ssh, 0, True
  WScript.Sleep 10000
Loop

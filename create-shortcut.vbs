Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = oWS.SpecialFolders("Desktop") & "\Options Trading App.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "C:\options-trading-companion\start.bat"
oLink.WorkingDirectory = "C:\options-trading-companion"
oLink.Description = "Start Options Trading Companion"
oLink.Save

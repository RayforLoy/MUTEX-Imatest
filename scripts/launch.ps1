$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
& "$taskRoot\.venv\Scripts\pythonw.exe" -m mutex_imatest @args


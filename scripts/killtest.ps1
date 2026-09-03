$ErrorActionPreference = "Continue"
Set-Location "d:\project\Rag_chatbot\backend"
$py = "..\.venv\Scripts\python.exe"
$DOC = "doc_b02fb622b193"

function Show($label) {
  Write-Output ""
  Write-Output "===== $label ====="
  & $py ..\scripts\dbstate.py $DOC
}

# Clean slate for this document only
& $py ..\scripts\resetdoc.py $DOC
Show "BEFORE: state before any extraction"

Write-Output ""
Write-Output "===== starting extraction, will hard-kill the process tree mid-document ====="
$p = Start-Process -FilePath $py -ArgumentList "-m","app.worker",$DOC -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\k1.log" -RedirectStandardError "$env:TEMP\k1err.log"
Start-Sleep -Milliseconds 850
$alive = -not $p.HasExited
Write-Output "killing PID $($p.Id) (tree). still running at kill time: $alive"
& taskkill /F /T /PID $p.Id 2>&1 | Out-String | ForEach-Object { $_.Trim() }
Start-Sleep -Milliseconds 400

Show "AFTER KILL: what survived the hard kill"

Write-Output ""
Write-Output "===== restarting - must resume, not start over ====="
& $py -m app.worker $DOC 2>&1 | Select-String -Pattern '\[done\]|resumed'

Show "AFTER RESUME: final state"

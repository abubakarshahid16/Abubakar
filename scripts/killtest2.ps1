$ErrorActionPreference = "Continue"
Set-Location "d:\project\Rag_chatbot\backend"
$py = "..\.venv\Scripts\python.exe"
$DOC = "doc_b02fb622b193"

function LCB {
  $out = & $py ..\scripts\dbstate.py $DOC
  if ($out -match 'last_completed_batch=(\d+)') { return [int]$Matches[1] } else { return -1 }
}
function PagesDone {
  $out = & $py ..\scripts\dbstate.py $DOC
  if ($out -match 'documents : page_count=\S+ pages_done=(\d+)') { return [int]$Matches[1] } else { return -1 }
}

foreach ($ms in 1000,1100,1200,1300,1400) {
  & $py ..\scripts\resetdoc.py $DOC | Out-Null
  $p = Start-Process -FilePath $py -ArgumentList "-m","app.worker",$DOC -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\k2.log" -RedirectStandardError "$env:TEMP\k2e.log"
  Start-Sleep -Milliseconds $ms
  & taskkill /F /T /PID $p.Id > $null 2>&1
  Start-Sleep -Milliseconds 300
  $lcb = LCB; $pd = PagesDone
  Write-Output "kill at ${ms}ms -> last_completed_batch=$lcb pages_done=$pd"
  if ($lcb -ge 0 -and $pd -lt 546) {
    Write-Output ""
    Write-Output "=== CAUGHT MID-DOCUMENT at ${ms}ms ==="
    Write-Output ""
    Write-Output "===== AFTER HARD KILL ====="
    & $py ..\scripts\dbstate.py $DOC
    Write-Output ""
    Write-Output "----- last 3 committed pages before the kill -----"
    & $py ..\scripts\pagesample.py $DOC tail
    Write-Output ""
    Write-Output "===== RESTART (must resume from batch $($lcb+1), not page 1) ====="
    & $py -m app.worker $DOC 2>&1 | Select-String -Pattern '\[done\]'
    Write-Output ""
    Write-Output "===== AFTER RESUME ====="
    & $py ..\scripts\dbstate.py $DOC
    break
  }
}

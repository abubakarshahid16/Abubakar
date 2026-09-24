<#
.SYNOPSIS
    Run pytest inside a specific git worktree, refusing if this script's
    working directory does not actually resolve to the worktree/branch it
    was written for.

.DESCRIPTION
    On 2026-09-24 a saved runner hardcoded to one worktree was reused
    unmodified against another; it silently tested the WRONG worktree's
    unmodified copy of an edited file and reported a passing result. This
    script calls scripts/worktree_guard.py before running anything, so that
    mistake fails loudly instead of reporting a false green.

.PARAMETER WorktreeDir
    Absolute path to the worktree's `backend` directory to run tests in.

.PARAMETER WorktreeName
    Expected worktree directory name (the git toplevel's own folder name),
    e.g. "b5-standards".

.PARAMETER Branch
    Expected git branch checked out in that worktree.

.EXAMPLE
    .\wt_pytest.ps1 -WorktreeDir "C:\project\saudi-aramco-rag-chatbot\.claude\worktrees\b5-standards\backend" `
                     -WorktreeName "b5-standards" -Branch "b5-standards" -- -q tests
#>
param(
    [Parameter(Mandatory = $true)] [string] $WorktreeDir,
    [Parameter(Mandatory = $true)] [string] $WorktreeName,
    [Parameter(Mandatory = $true)] [string] $Branch,
    [Parameter(ValueFromRemainingArguments = $true)] $PytestArgs
)

$repoRoot = "C:\project\saudi-aramco-rag-chatbot"
$env:OCR_MODEL_DIR = Join-Path $repoRoot "backend\models\ocr"
$env:EMBED_MODEL_DIR = Join-Path $repoRoot "backend\models\e5-small"

Set-Location $WorktreeDir

$guard = Join-Path (Split-Path $WorktreeDir -Parent) "scripts\worktree_guard.py"
& "$repoRoot\.venv\Scripts\python.exe" $guard $WorktreeName $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Error "worktree_guard refused - this runner is NOT testing the worktree/branch it was written for. See message above."
    exit 1
}

& "$repoRoot\.venv\Scripts\python.exe" -m pytest -p no:cacheprovider @PytestArgs 2>&1

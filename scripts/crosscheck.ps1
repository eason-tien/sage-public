# crosscheck.ps1 — 把同一份內容發給多個 CLI 做隔離式獨立審查（PowerShell 版）
# 用法：.\crosscheck.ps1 <待審文件> [輸出目錄]
# 關鍵：各 CLI 使用獨立 cwd，全部結束前不發布任何 review，降低互相錨定。
# 這是流程層隔離，不宣稱能防禦主動掃描整台主機的惡意 CLI。
# 注意：這是「模板」——各 CLI 呼叫語法因版本而異，首次用請先校準下方 Invoke-Reviewer。
# 安全：prompt 以變數整體當單一參數傳入，PowerShell 不對其做命令替換，無注入面。
param(
  [string]$ReviewFile,
  [string]$OutDir,
  [int]$MinSuccess = 0
)
$ErrorActionPreference = 'Continue'   # 用退出碼判定成敗，native stderr 不拋例外

function Write-Utf8NoBom([string]$Path, [string]$Text) {
  try {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
  } catch {
    throw "無法寫入審查證據 $Path：$($_.Exception.Message)"
  }
}
function Read-Utf8([string]$Path) {
  try {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
  } catch {
    throw "無法讀取審查輸入 $Path：$($_.Exception.Message)"
  }
}

if ([string]::IsNullOrWhiteSpace($ReviewFile) -or -not (Test-Path -LiteralPath $ReviewFile -PathType Leaf)) {
  Write-Host "用法：.\crosscheck.ps1 <待審文件(規格+Plan+契約)> [輸出目錄]"
  exit 1
}
if ([string]::IsNullOrWhiteSpace($OutDir)) {
  $OutDir = "crosscheck-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}
if ($MinSuccess -eq 0) {
  if ([string]::IsNullOrWhiteSpace($env:SAGE_MIN_REVIEWERS)) { $MinSuccess = 2 }
  elseif (-not [int]::TryParse($env:SAGE_MIN_REVIEWERS, [ref]$MinSuccess)) {
    Write-Host "SAGE_MIN_REVIEWERS 必須是 >= 2 的整數。"
    exit 1
  }
}
if ($MinSuccess -lt 2) {
  Write-Host "MinSuccess 必須是 >= 2 的整數（目前：$MinSuccess）。"
  exit 1
}
# [System.IO.File] API 以行程 cwd 解析相對路徑，Set-Location 不影響它——統一錨定到 PS location
if (-not [System.IO.Path]::IsPathRooted($ReviewFile)) { $ReviewFile = Join-Path (Get-Location).Path $ReviewFile }
if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path (Get-Location).Path $OutDir }

$SopDir = Split-Path -Parent $PSScriptRoot
$PromptFile = Join-Path $SopDir 'prompts\04-review-crosscheck.md'
New-Item -ItemType Directory -Path $OutDir -Force -ErrorAction Stop | Out-Null

# Reusing an output directory must not mix reviewers from an earlier run. Remove
# only artifacts managed by this script; preserve unrelated user files.
$managedArtifact = '^(?:review-.*\.md(?:\.err)?|failed-.*\.(?:out|err)|status\.tsv|_input\.md)$'
$cleanupFailed = $false
Get-ChildItem -LiteralPath $OutDir -File -ErrorAction Stop |
  Where-Object { $_.Name -match $managedArtifact } |
  ForEach-Object {
    try { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop }
    catch { $cleanupFailed = $true }
  }
if ($cleanupFailed) {
  Write-Host "無法清理重用輸出目錄中的舊審查產物；拒絕繼續。"
  exit 1
}

# 組合「審查提示詞 + 待審內容」成一份完整輸入
$InputFile = Join-Path $OutDir '_input.md'
try {
  $combined = (Read-Utf8 $PromptFile) + "`n`n---`n## 待審內容`n`n" + (Read-Utf8 $ReviewFile)
} catch {
  Write-Host "審查輸入組合失敗；未啟動 reviewer：$($_.Exception.Message)"
  exit 1
}

Write-Host "→ 待審輸入已在記憶體組合；完成前不發布中間 review"
Write-Host "→ 開始隔離式審查（獨立 cwd、延後集中發布）..."
Write-Host ""

# ───────────────────────────────────────────────
# 定義各 CLI 的「非互動」呼叫方式（讀 prompt → 出文字到 stdout）。
# 依你本機安裝/版本調整這個函數即可；新增 CLI 在 switch 加一支並寫進 $reviewers。
# ───────────────────────────────────────────────
function Invoke-Reviewer([string]$label, [string]$prompt) {
  # 呼叫語法已於本機實測可用。$null | …：給空 stdin，避免 CLI 等待互動輸入而卡住。
  switch ($label) {
    'claude' { $null | claude -p $prompt }
    'codex'  { $null | codex exec --skip-git-repo-check $prompt }   # 非 git 目錄也能跑
    'agy'    { $null | agy --print $prompt }
    'gemini' { $null | gemini -p $prompt }
    'grok'   { $null | grok -p $prompt }      # -p=--single 非互動（裸 grok 會開 TUI）
    default  { Write-Error "未定義的 reviewer：$label"; $global:LASTEXITCODE = 127 }   # 等價 bash 版 return 127，不誤報 ✓
  }
}
$reviewers = @('claude', 'codex')
if (Get-Command agy -ErrorAction SilentlyContinue) { $reviewers += 'agy' }
elseif (Get-Command gemini -ErrorAction SilentlyContinue) { $reviewers += 'gemini' }
$reviewers += 'grok'
$promptText = $combined

$statusRows = @("reviewer`tstatus`texit_code`tdetail")
$successCount = 0
$reviewRunDirs = @{}
foreach ($label in $reviewers) {
  $reviewDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sage-review-$label-" + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $reviewDir -Force -ErrorAction Stop | Out-Null
  $reviewRunDirs[$label] = $reviewDir
  $out = Join-Path $reviewDir "review-$label.md"
  $failedOut = Join-Path $reviewDir "failed-$label.out"
  $failedErr = Join-Path $reviewDir "failed-$label.err"
  Write-Host "  ▶ $label"
  if (Get-Command $label -ErrorAction SilentlyContinue) {
    $global:LASTEXITCODE = $null
    $errorCountBefore = $Error.Count
    # 不用 1> 檔案重定向：PS5.1 會寫成 UTF-16LE(BOM)，與 bash 版產出不一致；
    # 改為捕获後以 UTF-8 無 BOM 寫出（失敗時也保留部分輸出供診斷）
    Push-Location $reviewDir
    try { $revText = Invoke-Reviewer $label $promptText 2> $failedErr | Out-String }
    finally { Pop-Location }
    $pipelineOk = $?
    $code = if ($null -eq $LASTEXITCODE) { 127 } else { [int]$LASTEXITCODE }
    $stderrNonempty = (Test-Path $failedErr) -and (Get-Item $failedErr).Length -gt 0
    if ((-not $pipelineOk -or $Error.Count -gt $errorCountBefore -or $stderrNonempty) -and $code -eq 0) {
      $code = 1
    }
    # 成功判定 = 退出碼 0、stderr 空且 stdout 非空：function/alias 包裝的非原生 CLI 失敗時
    # 不設退出碼，只看 $LASTEXITCODE 會把 0-byte review 誤報「✓ 完成」（audit W-05 後半）
    if ($code -eq 0 -and -not [string]::IsNullOrWhiteSpace($revText)) {
      Write-Utf8NoBom $out $revText
      $successCount++
      $statusRows += "$label`tsuccess`t0`tnonempty output"
      Write-Host "    ✓ 完成（暫存；尚未發布）"
    } else {
      Write-Utf8NoBom $failedOut $revText
      $detail = if ($code -eq 0) { 'empty output' } else { 'execution failed' }
      if ($code -eq 0) { Write-Utf8NoBom $failedErr "reviewer returned empty output`n" }
      $statusRows += "$label`tfailed`t$code`t$detail"
      Write-Host "    ✗ $detail（診斷將在全部 reviewer 結束後發布）"
    }
    # stderr 歸一為 UTF-8 無 BOM；成功且空的清掉。
    if (Test-Path $failedErr) {
      if ((Get-Item $failedErr).Length -eq 0) { Remove-Item $failedErr -Force }
      else { Write-Utf8NoBom $failedErr (Get-Content $failedErr -Raw) }
    }
  }
  else {
    Write-Host "    ⊘ 未安裝 '$label'，跳過。可在 Invoke-Reviewer 調整。"
    Write-Utf8NoBom $failedOut ""
    Write-Utf8NoBom $failedErr "reviewer command not installed: $label`n"
    $statusRows += "$label`tmissing`t127`tcommand not installed"
  }
}
$statusFile = Join-Path $OutDir 'status.tsv'
$artifactFailure = $false
try {
  Write-Utf8NoBom $InputFile $combined
  Write-Utf8NoBom $statusFile (($statusRows -join "`n") + "`n")
  foreach ($label in $reviewers) {
    $reviewDir = $reviewRunDirs[$label]
    if (-not $reviewDir) { continue }
    Get-ChildItem -LiteralPath $reviewDir -File -ErrorAction Stop |
      Where-Object { $_.Name -match '^(?:review-.*\.md|failed-.*\.(?:out|err))$' } |
      Copy-Item -Destination $OutDir -Force -ErrorAction Stop
  }
} catch {
  $artifactFailure = $true
  Write-Host "✗ 審查證據發布失敗；拒絕宣告 quorum：$($_.Exception.Message)"
}
foreach ($reviewDir in $reviewRunDirs.Values) {
  try { Remove-Item -LiteralPath $reviewDir -Recurse -Force -ErrorAction Stop }
  catch {
    $artifactFailure = $true
    Write-Host "✗ 無法清理 reviewer 暫存目錄；拒絕宣告成功：$reviewDir"
  }
}
if ($artifactFailure) {
  exit 1
}

Write-Host ""
if ($successCount -lt $MinSuccess) {
  Write-Host "✗ 獨立審查 quorum 未達：$successCount / $MinSuccess；拒絕繼續。"
  Write-Host "狀態：$statusFile"
  exit 1
}
Write-Host "✓ 獨立審查 quorum：$successCount / $MinSuccess"
Write-Host "✓ 成功結果：$OutDir\review-*.md；狀態：$statusFile"
Write-Host ""
Write-Host "下一步（人工，不交給 AI 裁決）："
Write-Host "  1. 並排看各家意見"
Write-Host "  2. 標出『一致認同』vs『有分歧』的點"
Write-Host "  3. 分歧點列各方理由，由你拍板"
Write-Host "  4. 若由某個 Claude 匯總，要求它原樣列意見、標分歧、提建議但不裁決"
exit 0

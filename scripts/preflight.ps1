# preflight.ps1 — 進 /goal 前的環境前置檢查（PowerShell 版，等價 preflight.sh）
# 用法：.\preflight.ps1
# 作用：確認環境就緒，避免 /goal 前幾輪全耗在「為什麼跑不起來」
$ErrorActionPreference = 'SilentlyContinue'   # 逐條探測，個別失敗要繼續而非中斷

function Test-Cmd([string]$name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "═══ 環境前置檢查 ═══"
Write-Host ""
$ok = 0; $warn = 0

Write-Host "[1] 版本控制"
if (Test-Cmd git) { Write-Host "  ✓ git 可用"; $ok++ }
else { Write-Host "  ✗ git 不可用 —— 未就緒"; $warn++ }

# 先預設失敗再探測：git 缺失時命令根本沒跑，$LASTEXITCODE 殘留值不可信
$global:LASTEXITCODE = 1
git rev-parse --git-dir 1>$null 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "  ✓ 在 git 倉庫內（有回滾基線）"; $ok++ }
else { Write-Host "  ✗ 不在 git 倉庫內 —— 未就緒"; $warn++ }

Write-Host ""
Write-Host "[2] AI CLI（按你安裝的調整）"
foreach ($cli in @('claude', 'codex')) {
  if (Test-Cmd $cli) { Write-Host "  ✓ $cli 已安裝" }
  else { Write-Host "  ⊘ $cli 未安裝（如不需要可忽略）" }
}
if (Test-Cmd agy) { Write-Host "  ✓ agy 已安裝（目前 Google CLI）" }
else { Write-Host "  ⊘ agy 未安裝（目前 Google CLI；如不需要可忽略）" }
if (Test-Cmd gemini) { Write-Host "  ✓ gemini 已安裝（legacy Google CLI fallback）" }
else { Write-Host "  ⊘ gemini 未安裝（legacy Google CLI fallback；如不需要可忽略）" }
if (Test-Cmd grok) { Write-Host "  ✓ grok 已安裝" }
else { Write-Host "  ⊘ grok 未安裝（如不需要可忽略）" }

Write-Host ""
Write-Host "[3] 執行環境（按項目語言調整）"
$py = $null
foreach ($c in @('python', 'python3')) { if (Test-Cmd $c) { $py = $c; break } }
if ($py) {
  $ver = (& $py --version 2>&1 | Out-String).Trim()
  Write-Host "  ✓ $py：$ver"
  # 可選工具只提示不計 warn：非 Python 項目缺 pytest 不該把 preflight 打紅（工具擋假綠，不擋人）
  $global:LASTEXITCODE = 1
  & $py -m pytest --version 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) { Write-Host "  ✓ pytest 可用"; $ok++ }
  else { Write-Host "  ⊘ pytest 未安裝（Python 項目才需要；如不需要可忽略）" }
}
else { Write-Host "  ⊘ python 未安裝" }

Write-Host ""
Write-Host "[4] 工作目錄狀態"
$global:LASTEXITCODE = 1
git rev-parse --git-dir 1>$null 2>$null
if ($LASTEXITCODE -eq 0) {
  $status = git status --porcelain
  if ([string]::IsNullOrWhiteSpace($status)) { Write-Host "  ✓ 工作區乾淨（適合開始 /goal）" }
  else { Write-Host "  ⚠ 工作區有未提交改動 —— 建議先 commit，確保回滾基線乾淨"; $warn++ }
}

Write-Host ""
Write-Host "═══ 結果：$ok 項就緒，$warn 項需注意 ═══"
# 退出碼可機械判定（R1，等價 preflight.sh）：0=就緒、1=有需注意項
if ($warn -eq 0) { Write-Host "✓ 可以開始"; exit 0 }
else { Write-Host "⚠ 先處理上面標記項再進 /goal"; exit 1 }

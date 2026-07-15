# new-task.ps1 — 起一個新的 AI 輔助開發任務（PowerShell 版，等價 new-task.sh）
# 用法：.\new-task.ps1 <任務名> [目標目錄]
# 作用：建任務目錄、複製模板、git init + 起始 commit、生成 acceptance.txt
param(
  [string]$TaskName,
  [string]$BaseDir = (Get-Location).Path
)
$ErrorActionPreference = 'Stop'
# 相對 BaseDir 錨定到 PS location：[System.IO.File] API 按行程 cwd 解析，
# Set-Location 不改行程 cwd——經 in-process dispatcher（sage new x .）會中途炸掉留半成品
if (-not [System.IO.Path]::IsPathRooted($BaseDir)) { $BaseDir = Join-Path (Get-Location).Path $BaseDir }

function Write-Utf8NoBom([string]$Path, [string]$Text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

$SopDir = Split-Path -Parent $PSScriptRoot   # ai-dev-sop 根目錄

if ([string]::IsNullOrWhiteSpace($TaskName)) {
  Write-Host "用法：.\new-task.ps1 <任務名> [目標目錄]"
  Write-Host "範例：.\new-task.ps1 mes-comm-core C:\projects"
  exit 1
}

# 任務名校驗：只允許字母/數字/. _ -（一舉擋住路徑分隔 \ / 與 sed/特殊字元）
if ($TaskName -notmatch '^[A-Za-z0-9._-]+$') {
  Write-Host "✗ 任務名只允許字母/數字/. _ -（收到：$TaskName）"
  Write-Host "  例如：mes-comm-core；請勿使用 \ / 空格 & 等字元。"
  exit 1
}

$TaskDir = Join-Path $BaseDir $TaskName
if (Test-Path $TaskDir) {
  Write-Host "✗ 目錄已存在：$TaskDir"
  exit 1
}

# 建目錄前先校驗 SOP 模板源齊全：工具包若不完整，及早失敗，連目錄都不建
$required = @('prompts', 'checklists', 'templates\HANDOFF.md', 'templates\PROGRESS.md', 'templates\CONTRACT.md', 'templates\lessons.md')
foreach ($p in $required) {
  if (-not (Test-Path (Join-Path $SopDir $p))) {
    Write-Host "✗ SOP 模板缺失：$(Join-Path $SopDir $p)"
    Write-Host "  ai-dev-sop 目錄可能不完整，請確認工具包完整後重試。"
    exit 1
  }
}

Write-Host "→ 建立任務目錄：$TaskDir"
New-Item -ItemType Directory -Path $TaskDir | Out-Null
foreach ($d in @('sop', 'src', 'tests')) {
  New-Item -ItemType Directory -Path (Join-Path $TaskDir $d) | Out-Null
}

Write-Host "→ 複製提示詞模板與 checklist 到 sop\"
Copy-Item -Recurse (Join-Path $SopDir 'prompts')    (Join-Path $TaskDir 'sop\prompts')
Copy-Item -Recurse (Join-Path $SopDir 'checklists') (Join-Path $TaskDir 'sop\checklists')
foreach ($f in @('HANDOFF.md', 'PROGRESS.md', 'CONTRACT.md', 'lessons.md')) {
  Copy-Item (Join-Path $SopDir "templates\$f") (Join-Path $TaskDir "sop\$f")
}

# 把任務名填進模板標題：用 .NET 讀寫 UTF-8 無 BOM（避免 CJK 亂碼）；
# .Replace 為字面替換（非 regex），任務名已校驗無特殊字元。
foreach ($f in @('HANDOFF.md', 'PROGRESS.md', 'CONTRACT.md', 'lessons.md')) {
  $fp = Join-Path $TaskDir "sop\$f"
  $txt = [System.IO.File]::ReadAllText($fp, [System.Text.Encoding]::UTF8)
  $txt = $txt.Replace('[任務名]', $TaskName)
  Write-Utf8NoBom $fp $txt
}

# 生成 acceptance.txt 骨架（小任務快車道直接填它 → verify.ps1 跑它）
$acc = @"
# 驗收命令清單：一行一條可機械檢驗的命令；退出碼 0=通過、非0=不通過。
# verify.ps1 會逐條跑並留證據。以 # 開頭或空白的行會被略過。
# 每行在獨立子行程執行、行間互不影響：cd/變數不跨行。多步驟請包成 .ps1 用 exit 傳碼（; 不短路）。
# 注意：全部是註解（0 條命令）的驗收集 verify 會拒絕認證（exit 2）——先填真驗收。
# 用 PowerShell/原生命令（bash 專屬語法請改用 verify.sh）。範例：
#   python -m pytest -q
#   python -m coverage report --fail-under=90
"@
Write-Utf8NoBom (Join-Path $TaskDir 'acceptance.txt') $acc

Write-Host "→ git init + 起始 commit（回滾保護的起點）"
# git 會把警告(如 CRLF 提示)寫到 stderr；在 EAP=Stop 且輸出被重定向時，這些良性警告
# 會被當成 NativeCommandError 誤拋。故 git 區塊改用 Continue + 退出碼判定。
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "✗ git 不可用——無法建立回滾基線（R3），中止。已建立的目錄請手動處理：$TaskDir"
  exit 1
}
$eapSaved = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
git -C $TaskDir init -q
git -C $TaskDir config core.autocrlf false   # 任務倉庫內關閉轉換，消除 CRLF 警告源
$email = git -C $TaskDir config user.email
if (-not $email) {
  git -C $TaskDir config user.email "ai-dev-sop@localhost.invalid"
  git -C $TaskDir config user.name  "ai-dev-sop"
  Write-Host "  （已為本倉庫設預設 git 身份，可日後用 git config 改）"
}
$gitignore = @"
__pycache__/
*.pyc
.venv/
node_modules/
*.log
"@
Write-Utf8NoBom (Join-Path $TaskDir '.gitignore') $gitignore
git -C $TaskDir add -A
# 用 -F + UTF-8 檔避免 PowerShell 傳 CJK 參數亂碼
$tmp = New-TemporaryFile
Write-Utf8NoBom $tmp.FullName "chore: 任務 $TaskName 起始骨架（SOP 模板 + git 回滾基線）"
$global:LASTEXITCODE = 1   # 預設失敗：commit 沒真的跑（如 git 半路壞掉）不能沿用殘留 0
git -C $TaskDir commit -q -F $tmp.FullName
$commitCode = $LASTEXITCODE
Remove-Item $tmp.FullName -ErrorAction SilentlyContinue
$ErrorActionPreference = $eapSaved
if ($commitCode -ne 0) {
  Write-Host "✗ git 起始 commit 失敗(exit $commitCode)——回滾基線未建立（R3），請手動檢查 $TaskDir"
  exit 1   # 等價 bash 版 set -e：起始 commit 失敗不能回報「任務已建立」exit 0
}

Write-Host ""
Write-Host "✓ 任務已建立：$TaskDir"
Write-Host ""
Write-Host "下一步："
Write-Host "  1. cd $TaskDir"
Write-Host "  2. 編輯 sop\prompts\01-spec.md 填規格 + 驗收方式"
Write-Host "  3. 把驗收命令填進 acceptance.txt，邊做邊用 verify.ps1 驗"
Write-Host ""
Write-Host "  ▸ 小任務快車道：填 01-spec(目標+驗收) → 幹活 → verify.ps1，三步收工"
Write-Host "  ▸ 大任務/高風險才升級：A 拆分 + 接縫契約 + 多 CLI 審 + 六道閘"
Write-Host "    （見 README「兩條路徑」與 checklists\）"

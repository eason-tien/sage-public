# retro.ps1 — 30 秒執行後檢討：生成一則 3 問骨架到 sage 倉 retro/（PowerShell 版，等價 retro.sh）
# 用法：.\retro.ps1 <任務名> [目標目錄]
# 定位：提醒與便利，不是閘——不裁定任何流程，verify/lock 不依賴它（工具不是監獄）。
param([string]$TaskName, [string]$OutDir = '')
$ErrorActionPreference = 'Stop'
# 相對目錄錨定到 PS location：[System.IO.File] API 按行程 cwd 解析，Set-Location 不改行程 cwd
if (-not [string]::IsNullOrWhiteSpace($OutDir) -and -not [System.IO.Path]::IsPathRooted($OutDir)) {
  $OutDir = Join-Path (Get-Location).Path $OutDir
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

$SopDir = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Join-Path $SopDir 'retro' }

if ([string]::IsNullOrWhiteSpace($TaskName)) {
  Write-Host '用法：.\retro.ps1 <任務名> [目標目錄]'
  Write-Host '範例：sage retro mes-comm-core   # 生成 retro/YYYYMMDD-HHMM-mes-comm-core.md'
  exit 1
}

# 任務名校驗（同 new-task 字元集，另禁前導 -：與 bash 版對齊）
if ($TaskName -notmatch '^[A-Za-z0-9._][A-Za-z0-9._-]*$') {
  Write-Host "✗ 任務名只允許字母/數字/. _ -（收到：$TaskName）"
  exit 1
}

# UTC + InvariantCulture：非 Gregorian 文化下檔名仍為西曆零填充（同 acceptance-lock.ps1 先例）
$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmm', [System.Globalization.CultureInfo]::InvariantCulture)
$file = Join-Path $OutDir "$stamp-$TaskName.md"
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

if (Test-Path -LiteralPath $file) {
  Write-Host "同分鐘已有這個任務的檢討，直接編輯它：$file"
  exit 1
}

# 骨架用 LF 拼接後以 UTF-8 無 BOM 寫出——與 retro.sh 生成物位元組一致（雙平台等價）
$skeleton = @(
  "# retro — $TaskName（$stamp UTC）",
  '## 1. 這次哪裡卡了？',
  '',
  '## 2. 驗收哪條寫得好或爛？',
  '',
  '## 3. SOP 本身哪裡摩擦？',
  '',
  '值不值：'
) -join "`n"
Write-Utf8NoBom $file ($skeleton + "`n")

Write-Host "✓ 檢討骨架：$file"
Write-Host '  30 秒填完即可；週彙整見 checklists/weekly-retro.md。'
exit 0

# verify.ps1 — 跑驗收命令並留下真實證據（PowerShell 版，等價 verify.sh）
# 用法：.\verify.ps1 [acceptance.txt]
# 核心：這是「你親自跑、看真綠」的工具，不信 AI 自報的綠。
# 注意：每行在獨立的子 PowerShell 行程執行（等價 verify.sh 的子 bash 隔離）：
#       驗收行裡的 exit/cd/變數賦值只影響該子行程，不會終結 verify、不會動計數器；
#       行間完全獨立——跨行狀態請包成 .ps1 腳本用 exit 傳碼（注意 ; 不短路：中段原生命令失敗會被後段洗綠；cmdlet 錯誤仍會判紅）。
#       請填 PowerShell/原生命令；bash 專屬語法（如 && 與 grep 管道）請改用 verify.sh。
#       判定：原生命令看退出碼（非零折疊為 1）；純 cmdlet 看錯誤；輸出中任一布林 False
#       視為不通過（Test-Path 之類的檢查式驗收因此可靠）。
param([string]$AcceptFile = "acceptance.txt", [switch]$AllowUnlocked)
$ErrorActionPreference = 'Continue'   # 逐條跑可能失敗的命令，用退出碼/錯誤計數判定，不中斷

function Write-Utf8NoBom([string]$Path, [string]$Text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

# 驗收命令可能 cd 到別處；證據日誌路徑須固定在「呼叫本腳本當下的目錄」，
# 故先鎖存呼叫端絕對路徑，之後每條命令跑完都會還原到此目錄，不受其影響。
$InvokeDir = (Get-Location).Path
$AcceptOriginal = if ([System.IO.Path]::IsPathRooted($AcceptFile)) { $AcceptFile } else { Join-Path $InvokeDir $AcceptFile }

if (-not (Test-Path $AcceptFile)) {
  Write-Host "找不到驗收命令清單。請建立 $AcceptFile，一行一條可執行的驗收命令，例如："
  Write-Host ""
  Write-Host "  python -m pytest -q"
  Write-Host "  python -m coverage report --fail-under=90"
  Write-Host ""
  Write-Host "每條命令的退出碼 0 = 通過，非 0 = 不通過。"
  exit 1
}

$SnapshotDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sage-acceptance-" + [Guid]::NewGuid().ToString('N'))
$SnapshotAccept = Join-Path $SnapshotDir 'acceptance.txt'
function Remove-AcceptanceSnapshot() {
  Remove-Item -LiteralPath $SnapshotDir -Recurse -Force -ErrorAction SilentlyContinue
}
try {
  New-Item -ItemType Directory -Path $SnapshotDir -ErrorAction Stop | Out-Null
  [System.IO.File]::WriteAllBytes($SnapshotAccept, [System.IO.File]::ReadAllBytes($AcceptOriginal))
} catch {
  Remove-AcceptanceSnapshot
  Write-Host "無法建立驗收檔不可變 snapshot；拒絕執行。"
  exit 2
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $InvokeDir "verify-$stamp.log"
try {
  Write-Utf8NoBom $log ""   # 建空日誌（UTF-8 無 BOM）
} catch {
  Remove-AcceptanceSnapshot
  Write-Host "無法建立驗收證據日誌；拒絕執行。"
  exit 2
}
$EvidenceEncoding = New-Object System.Text.UTF8Encoding($false)
function Append-Evidence([string]$Text) {
  try {
    [System.IO.File]::AppendAllText($log, $Text, $EvidenceEncoding)
  } catch {
    Remove-AcceptanceSnapshot
    Write-Host "✗ 驗收證據日誌寫入失敗；拒絕認證全綠。"
    exit 2
  }
}
function Log([string]$s) {
  Write-Host $s
  Append-Evidence ($s + [Environment]::NewLine)
}

Log "═══ 最終驗收（真實執行，留證據）═══"
Log "時間：$(Get-Date)"
Log ""

# 防篡改閘：驗收集若被改動則拒絕認證綠（acceptance set tamper-check, R9）
# 委派給 acceptance-lock.ps1 check，雜湊邏輯只存一處（DRY，含 CRLF 歸一化）
$lockFile = "$AcceptOriginal.lock"
if (Test-Path $lockFile) {
  try {
    [System.IO.File]::WriteAllBytes("$SnapshotAccept.lock", [System.IO.File]::ReadAllBytes($lockFile))
  } catch {
    Remove-AcceptanceSnapshot
    Log "✗ 驗收鎖無法建立不可變 snapshot；未執行任何驗收命令。"
    exit 2
  }
  & (Join-Path $PSScriptRoot 'acceptance-lock.ps1') check $SnapshotAccept *> $null
  if ($LASTEXITCODE -ne 0) {
    Log "✗ 驗收集已被改動（ACCEPTANCE TAMPERED）——拒絕認證綠，未執行任何驗收命令。"
    Log "  → 跑 acceptance-lock.ps1 check $AcceptFile 看詳情；有意改驗收請重新 lock，否則視為假綠攻擊。"
    Remove-AcceptanceSnapshot
    exit 2
  }
  Log "驗收集未變（acceptance-lock check ✓）"
} elseif ($AllowUnlocked) {
  Log "（無 $lockFile：以 -AllowUnlocked 顯式跳過 R9 防篡改——僅供臨時/throwaway。）"
} else {
  Log "✗ 無 $lockFile：R9 要求驗收集先鎖定（fail-closed）。先跑 acceptance-lock.ps1 lock $AcceptFile，"
  Log "  或明確加 -AllowUnlocked 跳過（不建議：等於 fail-open）。未認證，未執行任何驗收命令。"
  Remove-AcceptanceSnapshot
  exit 2
}
Log ""

# 子行程執行環境：用目前宿主同款 PowerShell 跑每一行（Windows PS5.1 → powershell；Core → pwsh）
$hostExe = $null
try { $hostExe = (Get-Process -Id $PID).Path } catch { }
if (-not $hostExe) { $hostExe = if ($PSVersionTable.PSEdition -eq 'Core') { 'pwsh' } else { 'powershell' } }
# wrapper 在子行程內執行驗收行（經 $env:SAGE_VERIFY_CMD 傳入，避免引號轉義地獄）：
# - 原生命令設了 $LASTEXITCODE → 以退出碼裁定（寫 stderr 但 exit 0 仍算過，不誤殺 pytest）；
#   非零一律折疊為 exit 1——Unix 上行程退出碼只有 8 位元，否則 exit 256 會被截斷成 0 假綠
# - 純 cmdlet：非終止錯誤（$Error）→ 不通過
# - 輸出中【任一】元素是 [bool]$false → 不通過（Test-Path 缺檔、多路徑檢查都不再假綠）
# - 驗收行裡的 exit 只終結子行程，其退出碼照常參與裁定
$wrapper = @'
$ErrorActionPreference = 'Continue'
$null = Set-Location -LiteralPath $env:SAGE_VERIFY_CWD
$threw = $false
try { $o = Invoke-Expression $env:SAGE_VERIFY_CMD 2>&1 } catch { $threw = $true; $_ | Out-String | Write-Output }
$c = $LASTEXITCODE
if ($null -ne $o) { $o | Out-String | Write-Output }
if ($threw) { exit 1 }
foreach ($e in @($o)) { if ($e -is [bool] -and -not $e) { exit 1 } }
if ($null -ne $c) { if ($c -eq 0) { exit 0 } else { exit 1 } }
if ($Error.Count -gt 0) { exit 1 }
exit 0
'@
# 以 -EncodedCommand 傳遞 wrapper：避開 PS5.1/pwsh 對多行 -Command 引數的引號/換行轉義差異
$wrapperEnc = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($wrapper))

$pass = 0; $fail = 0; $n = 0
foreach ($cmd in (Get-Content -LiteralPath $SnapshotAccept -Encoding UTF8)) {
  # 略過空白行與註解行（容忍前導空白）
  if ($cmd -match '^\s*$' -or $cmd -match '^\s*#') { continue }
  $n++
  Log "──────────────────────────────────────"
  Log "[$n] `$ $cmd"

  $env:SAGE_VERIFY_CMD = $cmd
  $env:SAGE_VERIFY_CWD = $InvokeDir
  # $null | ……：給子行程空 stdin（等價 verify.sh 的 </dev/null），會讀 stdin 的驗收行立即 EOF 不掛死。
  # 先清 $LASTEXITCODE：子行程若沒能啟動（$code 仍為 $null）→ 視為 127 不通過（fail-closed），
  # 絕不沿用上一條命令殘留的 0 假綠。
  $global:LASTEXITCODE = $null
  $out = $null
  try {
    $out = $null | & $hostExe -NoProfile -EncodedCommand $wrapperEnc 2>&1
    $code = $LASTEXITCODE
  }
  finally {
    # PowerShell 的 location 是目前 runspace 狀態；無論驗收命令或宿主如何結束，
    # 都在寫日誌與執行下一行前恢復呼叫目錄，避免證據分裂或後續命令繼承位移。
    Set-Location -LiteralPath $InvokeDir
  }
  if ($null -eq $code) { $code = 127 }
  if ($out) {
    Append-Evidence ((($out | Out-String).TrimEnd()) + [Environment]::NewLine)
  }
  if ($code -ne 0) {
    Log "    → 退出碼 $code ✗ 不通過"
    $fail++
  }
  else {
    Log "    → 通過 ✓"
    $pass++
  }
}
Remove-Item Env:\SAGE_VERIFY_CMD -ErrorAction SilentlyContinue
Remove-Item Env:\SAGE_VERIFY_CWD -ErrorAction SilentlyContinue

Log ""
Log "═══ 驗收結果：$pass 通過 / $fail 不通過（共 $n 條）═══"
Log "完整證據：$log"
Log ""
if ($n -eq 0) {
  Log "✗ 0 條驗收命令——空驗收集不可認證（R1 要求至少一條可機械判定）。填好 $AcceptFile 再來。"
  Remove-AcceptanceSnapshot
  exit 2
}
if ($fail -eq 0) {
  Log "✓ 全綠（且是你親跑的真綠）。可考慮合入 main。"
  Log "  30 秒檢討（可選）：sage retro <任務名>——落到 sage 倉 retro/，供週迭代彙整。"
  Remove-AcceptanceSnapshot
  exit 0
}
else {
  Log "✗ 有未通過項。git 回滾，修條件或 Plan，重來。不要合入。"
  Remove-AcceptanceSnapshot
  exit 1
}

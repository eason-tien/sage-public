# selftest.ps1 — 自检：在臨時目錄驗證本包 .ps1 腳本在本機能否正常工作（不調用真實 AI CLI）
# 用法：.\selftest.ps1   （全部通過 exit 0；任一檢查失敗 exit 1）
$ErrorActionPreference = 'Continue'

$SopDir = Split-Path -Parent $PSScriptRoot
$Scr = Join-Path $SopDir 'scripts'
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("aidevsop-selftest-" + [System.Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
function W($p, $t) { [System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($false))) }

$pass = 0; $fail = 0
function OK($m) { Write-Host "  ✓ $m"; $script:pass++ }
function NG($m) { Write-Host "  ✗ $m"; $script:fail++ }
function EQ($m, $a, $e) { if ("$a" -eq "$e") { OK $m } else { NG "$m（得到 [$a] 期望 [$e]）" } }

try {
  Write-Host "═══ ai-dev-sop 自检（PowerShell）═══"
  Write-Host "臨時目錄：$Tmp"
  Write-Host ""

  Write-Host "[new-task.ps1]"
  & "$Scr\new-task.ps1" demo-x $Tmp *> $null; $rc = $LASTEXITCODE
  EQ "正常任務名 → exit 0" $rc 0
  if (Test-Path (Join-Path $Tmp 'demo-x\sop\prompts\01-spec.md')) { OK "目錄結構正確" } else { NG "目錄結構缺失" }
  $h = [System.IO.File]::ReadAllText((Join-Path $Tmp 'demo-x\sop\HANDOFF.md'), [System.Text.Encoding]::UTF8)
  if ($h.Contains('[任務名]')) { NG "占位符未替換" } else { OK "占位符已替換" }
  if (Test-Path (Join-Path $Tmp 'demo-x\acceptance.txt')) { OK "已生成 acceptance.txt" } else { NG "缺 acceptance.txt" }
  $lmp = Join-Path $Tmp 'demo-x\sop\lessons.md'
  if (Test-Path $lmp) {
    $lm = [System.IO.File]::ReadAllText($lmp, [System.Text.Encoding]::UTF8)
    if ($lm.Contains('[' + '任務名' + ']')) { NG "lessons.md 占位符未替換" } else { OK "已複製 lessons.md 且占位符已替換（非孤兒）" }
  } else { NG "缺 sop/lessons.md（孤兒模板未修）" }
  & "$Scr\new-task.ps1" "bad/name" $Tmp *> $null; $rc = $LASTEXITCODE
  EQ "非法任務名 → exit 1（拒絕）" $rc 1

  Write-Host ""
  Write-Host "[verify.ps1]"
  # Invoke the current PowerShell executable so the native exit-code checks work
  # identically on Windows, macOS, and Linux (where cmd.exe is unavailable).
  W (Join-Path $Tmp 'acc_ok.txt') "pwsh -NoProfile -Command `"exit 0`"`nWrite-Output ok`n"
  W (Join-Path $Tmp 'acc_ng.txt') "pwsh -NoProfile -Command `"exit 0`"`npwsh -NoProfile -Command `"exit 3`"`n"
  Push-Location $Tmp
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_ok.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "全部通過(+-AllowUnlocked) → exit 0" $rc 0
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_ng.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "有失敗(+-AllowUnlocked) → exit 1" $rc 1
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_ok.txt') *> $null; $rc = $LASTEXITCODE
  EQ "無鎖無 override → 拒絕 fail-closed exit 2 (C2)" $rc 2

  # —— 假綠面負向案例（AUDIT 2026-07-13 迭代 1）——
  $vOut = & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_ok.txt') -AllowUnlocked *>&1 | Out-String
  if ($vOut -match 'sage retro') { OK "全綠訊息含 retro 提示（提醒非強制）" } else { NG "全綠訊息缺 retro 提示" }
  W (Join-Path $Tmp 'acc_exit.txt') "exit 0`npwsh -NoProfile -Command `"exit 3`"`n"
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_exit.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "驗收行含 exit 不劫持 runner，後續失敗行照計 → exit 1 (W-02)" $rc 1
  W (Join-Path $Tmp 'acc_bool.txt') "Test-Path (Join-Path '$Tmp' 'no-such-file.xyz')`n"
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_bool.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "布林 False 輸出（Test-Path 缺檔）→ 不通過 exit 1 (W-01)" $rc 1
  W (Join-Path $Tmp 'acc_bool2.txt') "Test-Path (Join-Path '$Tmp' 'no-such-file.xyz'), '$Tmp'`n"
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_bool2.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "多路徑檢查中任一 False（非末位）→ 不通過 exit 1 (W-01 補強)" $rc 1
  W (Join-Path $Tmp 'exit256.ps1') "exit 256`n"
  W (Join-Path $Tmp 'acc_256.txt') ("& '" + (Join-Path $Tmp 'exit256.ps1') + "'`n")
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_256.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "PS 腳本型驗收 exit 256 不被 8-bit 截斷洗綠 → 不通過 exit 1" $rc 1
  W (Join-Path $Tmp 'acc_stdin.txt') "pwsh -NoProfile -Command `"[Console]::In.ReadToEnd() | Out-Null; exit 0`"`npwsh -NoProfile -Command `"exit 0`"`n"
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_stdin.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "會讀 stdin 的驗收行立即 EOF 不掛死 → exit 0" $rc 0
  W (Join-Path $Tmp 'acc_wash.txt') "pwsh -NoProfile -Command `"exit 3`"`n`$fail = 0`n"
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_wash.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "驗收行賦值洗不掉計數器 → exit 1 (B-02 等價)" $rc 1
  W (Join-Path $Tmp 'acc_empty.txt') "# 只有註解，一條驗收都沒有`n"
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_empty.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "空驗收集不可認證 → exit 2 (B-04 等價)" $rc 2
  $snapshotAcceptance = Join-Path $Tmp 'acc_snapshot.txt'
  $snapshotQuoted = $snapshotAcceptance.Replace("'", "''")
  W $snapshotAcceptance ("[System.IO.File]::WriteAllText('" + $snapshotQuoted + "', 'Write-Output true')`nexit 1`n")
  & "$Scr\acceptance-lock.ps1" lock $snapshotAcceptance *> $null
  & "$Scr\verify.ps1" $snapshotAcceptance *> $null; $rc = $LASTEXITCODE
  EQ "驗收第一行換掉原檔也不能跳過 snapshot 內後續 exit 1" $rc 1

  $logFailDir = Join-Path $Tmp 'verify-log-fail'
  New-Item -ItemType Directory -Path $logFailDir -Force | Out-Null
  $logFailQuoted = $logFailDir.Replace("'", "''")
  $logFailureCommand = "`$p = Get-ChildItem -LiteralPath '$logFailQuoted' -Filter 'verify-*.log' -File | Select-Object -First 1; Remove-Item -LiteralPath `$p.FullName -Force; New-Item -ItemType Directory -Path `$p.FullName | Out-Null"
  W (Join-Path $logFailDir 'acceptance.txt') ($logFailureCommand + "`n")
  Push-Location $logFailDir
  & "$Scr\verify.ps1" (Join-Path $logFailDir 'acceptance.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  Pop-Location
  EQ "驗收證據追加失敗 → fail-closed exit 2" $rc 2
  Remove-Item -LiteralPath $logFailDir -Recurse -Force
  Pop-Location

  Write-Host ""
  Write-Host "[retro.ps1]"
  & "$Scr\retro.ps1" demo-x (Join-Path $Tmp 'retro-out') *> $null; $rc = $LASTEXITCODE
  EQ "正常生成檢討骨架 → exit 0" $rc 0
  $rf = Get-ChildItem (Join-Path $Tmp 'retro-out') -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($rf -and $rf.Name -match '^\d{8}-\d{4}-demo-x\.md$') { OK "檔名為 UTC 零填充格式" } else { NG "檔名格式錯（$(if ($rf) { $rf.Name } else { '無檔' })）" }
  if ($rf) {
    $rtxt = [System.IO.File]::ReadAllText($rf.FullName, [System.Text.Encoding]::UTF8)
    if ($rtxt.Contains('這次哪裡卡了') -and $rtxt.Contains('驗收哪條寫得好或爛') -and $rtxt.Contains('SOP 本身哪裡摩擦') -and $rtxt.Contains('值不值')) { OK "骨架含 3 問＋值不值" } else { NG "骨架內容缺欄位" }
  } else { NG "無生成檔可驗內容" }
  & "$Scr\retro.ps1" 'bad/name' (Join-Path $Tmp 'retro-out') *> $null; $rc = $LASTEXITCODE
  EQ "非法任務名 → exit 1（拒絕）" $rc 1
  # 萬用字元路徑撞檔看守（LiteralPath）：預建同分鐘目標檔含哨兵，retro 必須拒絕且不覆蓋。
  # 分鐘邊界可能讓第一次嘗試落空（檔名戳不同），故最多試兩次——同分鐘內必有一次命中。
  $rbDir = Join-Path $Tmp 'r[1]out'
  New-Item -ItemType Directory -Path $rbDir -Force | Out-Null
  $collGuard = $false
  foreach ($try in 1..2) {
    $st = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmm', [System.Globalization.CultureInfo]::InvariantCulture)
    $preFile = Join-Path $rbDir "$st-demo-w.md"
    W $preFile "SENTINEL-KEEP-ME`n"
    & "$Scr\retro.ps1" demo-w $rbDir *> $null; $rc = $LASTEXITCODE
    $post = [System.IO.File]::ReadAllText($preFile, [System.Text.Encoding]::UTF8)
    if ($rc -eq 1 -and $post.Contains('SENTINEL-KEEP-ME')) { $collGuard = $true; break }
    if ($post.Contains('SENTINEL-KEEP-ME') -eq $false) { break }   # 被覆蓋：立即判失敗，不重試
  }
  if ($collGuard) { OK "萬用字元路徑同分鐘撞檔 → 拒絕且不覆蓋（LiteralPath）" } else { NG "萬用字元路徑撞檔守門失效（覆蓋或誤放行）" }
  $savedCulture2 = [System.Threading.Thread]::CurrentThread.CurrentCulture
  try {
    [System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::new('ar-SA')
    & "$Scr\retro.ps1" demo-cul (Join-Path $Tmp 'retro-out3') *> $null
  } finally { [System.Threading.Thread]::CurrentThread.CurrentCulture = $savedCulture2 }
  $rf3 = Get-ChildItem (Join-Path $Tmp 'retro-out3') -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($rf3 -and $rf3.Name -match '^\d{8}-' -and [int]$rf3.Name.Substring(0,4) -gt 2000) { OK "非 Gregorian 文化下檔名仍西曆零填充（InvariantCulture）" } else { NG "文化敏感檔名（$(if ($rf3) { $rf3.Name } else { '無檔' })）" }

  Write-Host ""
  Write-Host "[verify.ps1 驗收命令變更目錄]"
  $CwdCase = Join-Path $Tmp 'cwdcase'
  $Nested = Join-Path $CwdCase 'nested'
  New-Item -ItemType Directory -Path $Nested -Force | Out-Null
  $cwdCmd2 = "if ((Get-Location).Path -eq '$CwdCase') { Write-Output BACK_IN_INVOKE_DIR } else { Write-Output STILL_DISPLACED }"
  W (Join-Path $CwdCase 'acc_cwd.txt') "Set-Location -LiteralPath '$Nested'; Write-Output IN_NESTED`n$cwdCmd2`n"
  Push-Location $CwdCase
  & "$Scr\verify.ps1" (Join-Path $CwdCase 'acc_cwd.txt') -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  Pop-Location
  EQ "含 cd 的驗收命令仍全部通過 → exit 0" $rc 0
  $cwdLogs = @(Get-ChildItem -Path $CwdCase -Filter 'verify-*.log' -File -ErrorAction SilentlyContinue)
  EQ "呼叫目錄僅一份 verify-*.log" $cwdLogs.Count 1
  $nestedLogs = @(Get-ChildItem -Path $Nested -Filter 'verify-*.log' -File -ErrorAction SilentlyContinue)
  if ($nestedLogs.Count -eq 0) { OK "nested 目錄無分裂日誌" } else { NG "nested 目錄出現分裂日誌" }
  if ($cwdLogs.Count -eq 1) {
    # 每條命令的原始文字會被寫入 "[$n] $ $cmd" 標頭，所以命令原文中未觸發的分支文字
    # （如 STILL_DISPLACED）一定也會出現 1 次；要判斷位置是否真的還原，得看該記號是否
    # 「額外」以獨立輸出行出現：真的還原時 BACK_IN_INVOKE_DIR 會出現 2 次（標頭 + 實際
    # 輸出），STILL_DISPLACED 只會有標頭那 1 次。
    $inNestedCount = @(Select-String -Path $cwdLogs[0].FullName -Pattern 'IN_NESTED' -SimpleMatch -Encoding UTF8).Count
    $backCount = @(Select-String -Path $cwdLogs[0].FullName -Pattern 'BACK_IN_INVOKE_DIR' -SimpleMatch -Encoding UTF8).Count
    $displacedCount = @(Select-String -Path $cwdLogs[0].FullName -Pattern 'STILL_DISPLACED' -SimpleMatch -Encoding UTF8).Count
    $cwdLogContent = [System.IO.File]::ReadAllText($cwdLogs[0].FullName, [System.Text.Encoding]::UTF8)
    if ($inNestedCount -eq 2 -and $backCount -eq 2 -and $displacedCount -eq 1 `
        -and $cwdLogContent.Contains('2 通過 / 0 不通過')) {
      OK "單一日誌含兩條命令輸出、後續命令位置已還原、與最終彙總"
    } else {
      NG "日誌缺少命令輸出、位置未還原、或彙總缺失（nested=$inNestedCount back=$backCount displaced=$displacedCount summary=$($cwdLogContent.Contains('2 通過 / 0 不通過'))）"
    }
  } else {
    NG "無法驗證日誌內容（份數異常）"
  }

  Write-Host ""
  Write-Host "[acceptance-lock.ps1]"
  Push-Location $Tmp
  W (Join-Path $Tmp 'acc_lock.txt') "pwsh -NoProfile -Command `"exit 0`"`n"
  & "$Scr\acceptance-lock.ps1" lock (Join-Path $Tmp 'acc_lock.txt') *> $null; $rc = $LASTEXITCODE
  EQ "lock → exit 0" $rc 0
  if (Test-Path (Join-Path $Tmp 'acc_lock.txt.lock')) { OK "已生成 .lock" } else { NG "缺 .lock" }
  & "$Scr\acceptance-lock.ps1" check (Join-Path $Tmp 'acc_lock.txt') *> $null; $rc = $LASTEXITCODE
  EQ "未改 check → exit 0" $rc 0
  W (Join-Path $Tmp 'acc_lock.txt') "pwsh -NoProfile -Command `"exit 0`"`nWrite-Output sneaky`n"
  & "$Scr\acceptance-lock.ps1" check (Join-Path $Tmp 'acc_lock.txt') *> $null; $rc = $LASTEXITCODE
  EQ "改動後 check → exit 1（防篡改）" $rc 1
  & "$Scr\verify.ps1" (Join-Path $Tmp 'acc_lock.txt') *> $null; $rc = $LASTEXITCODE
  EQ "驗收集被改 → verify 拒絕認證 exit 2" $rc 2
  & "$Scr\acceptance-lock.ps1" lock (Join-Path $Tmp 'acc_lock.txt') *> $null; $rc = $LASTEXITCODE
  EQ "已鎖再 lock → exit 1（拒靜默重鎖 C1）" $rc 1
  & "$Scr\acceptance-lock.ps1" relock (Join-Path $Tmp 'acc_lock.txt') *> $null; $rc = $LASTEXITCODE
  EQ "relock → exit 0（顯式重鎖）" $rc 0
  $loneCr = Join-Path $Tmp 'acc_lone_cr.txt'
  [System.IO.File]::WriteAllBytes($loneCr, [System.Text.Encoding]::UTF8.GetBytes("exit 1`n"))
  & "$Scr\acceptance-lock.ps1" lock $loneCr *> $null; $rc = $LASTEXITCODE
  EQ "lone CR 基線 lock → exit 0" $rc 0
  [System.IO.File]::WriteAllBytes($loneCr, [System.Text.Encoding]::UTF8.GetBytes("exit`r 1`n"))
  & "$Scr\acceptance-lock.ps1" check $loneCr *> $null; $rc = $LASTEXITCODE
  EQ "embedded lone CR 不能共用原 hash → exit 1" $rc 1
  & "$Scr\verify.ps1" $loneCr *> $null; $rc = $LASTEXITCODE
  EQ "lone CR 篡改後 verify 拒絕 → exit 2" $rc 2
  $ts = ((Get-Content (Join-Path $Tmp 'acc_lock.txt.lock') -TotalCount 1) -split '\s+')[1]
  if ($ts -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$') { OK "鎖時間戳為 UTC Z 格式（雙平台一致）" } else { NG "鎖時間戳非 UTC Z 格式（$ts）" }
  Pop-Location

  Write-Host ""
  Write-Host "[preflight.ps1]"
  & "$Scr\preflight.ps1" *> $null; $rc = $LASTEXITCODE
  if ($rc -eq 0 -or $rc -eq 1) { OK "preflight 退出碼可機械判定（0=就緒/1=需注意）" } else { NG "preflight 退出碼異常（$rc）" }
  New-Item -ItemType Directory -Path (Join-Path $Tmp 'nogit') -Force | Out-Null
  Push-Location (Join-Path $Tmp 'nogit')
  & "$Scr\preflight.ps1" *> $null; $rc = $LASTEXITCODE
  Pop-Location
  EQ "非 git 目錄（必有 warn）→ exit 1 (B-10 映射釘死)" $rc 1

  Write-Host ""
  Write-Host "[sage.ps1 dispatcher]"
  . (Join-Path $SopDir 'sage.ps1')
  # 規則正文看守：R1–R9 逐條 + 關鍵機制詞（單一 'R9' 比對是空殼閘）
  $rulesOut = Invoke-Sage rules | Out-String
  $rulesMissing = @()
  foreach ($i in 1..9) { if ($rulesOut -notmatch "R$i") { $rulesMissing += "R$i" } }
  if ($rulesOut -notmatch 'acceptance-lock') { $rulesMissing += 'acceptance-lock' }
  if ($rulesOut -notmatch 'fail-closed') { $rulesMissing += 'fail-closed' }
  if ($rulesMissing.Count -eq 0) { OK "sage rules 印出完整鐵律正文（R1–R9 + 機制詞，SAGE_RULES.md）" }
  else { NG "sage rules 正文缺: $($rulesMissing -join ' ') ——規則單一事實源斷鏈/被掏空" }
  Push-Location $Tmp
  W (Join-Path $Tmp 'acceptance.txt') "pwsh -NoProfile -Command `"exit 0`"`n"
  & "$Scr\acceptance-lock.ps1" lock 'acceptance.txt' *> $null
  Invoke-Sage check *> $null; $rc = $LASTEXITCODE
  EQ "sage check 不帶檔名走預設 acceptance.txt → exit 0 (W-04)" $rc 0
  $lockLine = Get-Content (Join-Path $Tmp 'acceptance.txt.lock') -TotalCount 1
  if (($lockLine -split '\s+')[2] -eq 'acceptance.txt') { OK ".lock 第三欄保留使用者原始路徑（不洩漏本機絕對路徑）" }
  else { NG ".lock 第三欄非原樣路徑（$lockLine）" }
  Invoke-Sage verify acceptance.txt -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "sage verify 帶 -AllowUnlocked 經 dispatcher 正確轉發（有鎖未改 → exit 0）" $rc 0
  Remove-Item (Join-Path $Tmp 'acceptance.txt.lock') -Force
  Invoke-Sage verify acceptance.txt -AllowUnlocked *> $null; $rc = $LASTEXITCODE
  EQ "sage verify -AllowUnlocked 無鎖 → exit 0（旗標未被吞，等價 bash --allow-unlocked）" $rc 0
  & "$Scr\new-task.ps1" demo-rel . *> $null; $rc = $LASTEXITCODE
  if ($rc -eq 0 -and (Test-Path (Join-Path $Tmp 'demo-rel\acceptance.txt'))) { OK "相對 BaseDir 的 new-task 完整建立（PS location 錨定）" }
  else { NG "相對 BaseDir 的 new-task 失敗（rc=$rc）" }
  Invoke-Sage retro demo-y (Join-Path $Tmp 'retro-out2') *> $null; $rc = $LASTEXITCODE
  if ($rc -eq 0 -and (Get-ChildItem (Join-Path $Tmp 'retro-out2') -Filter '*-demo-y.md' -ErrorAction SilentlyContinue)) { OK "sage retro 經 dispatcher 可用" } else { NG "dispatcher retro 失敗（rc=$rc）" }
  Pop-Location
  $savedCulture = [System.Threading.Thread]::CurrentThread.CurrentCulture
  try {
    [System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::new('ar-SA')
    W (Join-Path $Tmp 'acc_culture.txt') "pwsh -NoProfile -Command `"exit 0`"`n"
    & "$Scr\acceptance-lock.ps1" lock (Join-Path $Tmp 'acc_culture.txt') *> $null
  } finally { [System.Threading.Thread]::CurrentThread.CurrentCulture = $savedCulture }
  $ts2 = ((Get-Content (Join-Path $Tmp 'acc_culture.txt.lock') -TotalCount 1) -split '\s+')[1]
  if ($ts2 -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$' -and [int]($ts2.Substring(0,4)) -gt 2000) { OK "非 Gregorian 文化下鎖時間戳仍為西曆 UTC Z（InvariantCulture）" }
  else { NG "文化敏感時間戳（$ts2）" }
  $savedPath = $env:PATH
  try {
    $env:PATH = ''
    & "$Scr\new-task.ps1" demo-nogit $Tmp *> $null; $rc = $LASTEXITCODE
  } finally { $env:PATH = $savedPath }
  EQ "git 不可用時 new-task 不謊報成功 → exit 1 (W-09)" $rc 1

  Write-Host ""
  Write-Host "[crosscheck.ps1]（用樁 CLI，不調真實 AI）"
  W (Join-Path $Tmp 'rev.md') "# 待審內容（自检樣本）`n"
  $env:SAGE_STUB_LOG = Join-Path $Tmp 'stub-calls.log'
  function global:claude { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "claude $($args -join ' ')`n"); Write-Output 'stub-claude output'; $global:LASTEXITCODE = 0 }
  function global:codex { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "codex $($args -join ' ')`n"); Write-Output 'stub-codex output'; $global:LASTEXITCODE = 0 }
  function global:agy { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "agy $($args -join ' ')`n"); Write-Output 'stub-agy output'; $global:LASTEXITCODE = 0 }
  function global:gemini { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "gemini $($args -join ' ')`n"); Write-Output 'stub-gemini output'; $global:LASTEXITCODE = 0 }
  function global:grok { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "grok $($args -join ' ')`n"); Write-Output 'stub-grok output'; $global:LASTEXITCODE = 0 }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout') *> $null; $rc = $LASTEXITCODE
  EQ "正常執行 → exit 0" $rc 0
  $rcm = Join-Path $Tmp 'ccout\review-claude.md'
  if ((Test-Path $rcm) -and ((Get-Item $rcm).Length -gt 0)) { OK "產出 review-claude.md" } else { NG "缺 review 輸出" }
  if (Test-Path (Join-Path $Tmp 'ccout\review-claude.md.err')) { NG "空 .err 未清理" } else { OK "空 .err 已清理" }
  $calls = [System.IO.File]::ReadAllText($env:SAGE_STUB_LOG, [System.Text.Encoding]::UTF8)
  $ram = Join-Path $Tmp 'ccout\review-agy.md'
  if ($calls.Contains('agy --print ') -and (Test-Path $ram) -and ((Get-Item $ram).Length -gt 0)) { OK "Agy 使用 --print 並產出 review-agy.md" } else { NG "Agy adapter 或輸出缺失" }
  if ($calls.Contains('gemini ') -or (Test-Path (Join-Path $Tmp 'ccout\review-gemini.md'))) { NG "Agy 存在時仍調用了 legacy Gemini" } else { OK "Agy 存在時不調 legacy Gemini" }
  function global:claude { Write-Output 'ANCHOR_SECRET_FROM_CLAUDE'; $global:LASTEXITCODE = 0 }
  function global:codex {
    if (Test-Path (Join-Path (Get-Location).Path 'review-claude.md')) { Write-Output 'SAW_PRIOR_REVIEW_ANCHOR' }
    else { Write-Output 'ISOLATED_FROM_PRIOR_REVIEW' }
    $global:LASTEXITCODE = 0
  }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-isolation') *> $null; $rc = $LASTEXITCODE
  $isolatedReview = Join-Path $Tmp 'ccout-isolation\review-codex.md'
  $isolatedText = if (Test-Path $isolatedReview) { [System.IO.File]::ReadAllText($isolatedReview, [System.Text.Encoding]::UTF8) } else { '' }
  if ($rc -eq 0 -and $isolatedText.Contains('ISOLATED_FROM_PRIOR_REVIEW') -and -not $isolatedText.Contains('SAW_PRIOR_REVIEW_ANCHOR')) { OK "後續 reviewer cwd 看不到先前 review；全部完成後才集中發布" }
  else { NG "reviewer cwd/發布隔離失效" }
  function global:claude { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "claude $($args -join ' ')`n"); Write-Output 'stub-claude output'; $global:LASTEXITCODE = 0 }
  function global:codex { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "codex $($args -join ' ')`n"); Write-Output 'stub-codex output'; $global:LASTEXITCODE = 0 }

  Remove-Item Function:\global:agy -ErrorAction SilentlyContinue
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-reuse') *> $null; $rc = $LASTEXITCODE
  EQ "Agy 缺失時 Gemini fallback → exit 0" $rc 0
  W (Join-Path $Tmp 'ccout-reuse\unrelated.txt') "preserve me`n"
  function global:agy { [System.IO.File]::AppendAllText($env:SAGE_STUB_LOG, "agy $($args -join ' ')`n"); Write-Output 'stub-agy output'; $global:LASTEXITCODE = 0 }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-reuse') *> $null; $rc = $LASTEXITCODE
  EQ "重用輸出目錄切回 Agy → exit 0" $rc 0
  if (-not (Test-Path (Join-Path $Tmp 'ccout-reuse\review-gemini.md')) -and (Test-Path (Join-Path $Tmp 'ccout-reuse\review-agy.md'))) { OK "重用輸出目錄不殘留上一輪 Gemini 成功檔" } else { NG "重用輸出目錄混入上一輪 reviewer 產物" }
  if (Test-Path (Join-Path $Tmp 'ccout-reuse\unrelated.txt')) { OK "清理保留非腳本管理檔" } else { NG "清理誤刪使用者檔" }

  $publishFail = Join-Path $Tmp 'ccout-publish-fail'
  New-Item -ItemType Directory -Path (Join-Path $publishFail '_input.md') -Force | Out-Null
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') $publishFail *> $null; $rc = $LASTEXITCODE
  EQ "審查證據發布目標不可寫 → fail-closed exit 1" $rc 1

  & "$Scr\crosscheck.ps1" $Tmp (Join-Path $Tmp 'ccout-directory-input') *> $null; $rc = $LASTEXITCODE
  EQ "待審輸入是目錄 → 啟動 reviewer 前 fail-closed exit 1" $rc 1

  & "$Scr\crosscheck.ps1" *> $null; $rc = $LASTEXITCODE
  EQ "缺參數 → exit 1" $rc 1

  function global:claude { Write-Output 'partial-without-native-exit' }
  function global:codex { Write-Output 'partial-without-native-exit' }
  function global:agy { Write-Output 'partial-without-native-exit' }
  function global:grok { Write-Output 'partial-without-native-exit' }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-null-exit') *> $null; $rc = $LASTEXITCODE
  EQ "partial stdout + null LASTEXITCODE 不得算成功 → quorum exit 1" $rc 1
  function global:claude { Write-Output 'partial'; Write-Error 'stub failure'; $global:LASTEXITCODE = 0 }
  function global:codex { Write-Output 'partial'; Write-Error 'stub failure'; $global:LASTEXITCODE = 0 }
  function global:agy { Write-Output 'partial'; Write-Error 'stub failure'; $global:LASTEXITCODE = 0 }
  function global:grok { Write-Output 'partial'; Write-Error 'stub failure'; $global:LASTEXITCODE = 0 }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-errors') *> $null; $rc = $LASTEXITCODE
  EQ "partial stdout + PowerShell error 不得算成功 → quorum exit 1" $rc 1
  $nativePowerShellCommand = Get-Command pwsh -ErrorAction SilentlyContinue
  if ($null -eq $nativePowerShellCommand) { $nativePowerShellCommand = Get-Command powershell -ErrorAction Stop }
  $global:SageNativePowerShell = $nativePowerShellCommand.Source
  function global:claude { & $global:SageNativePowerShell -NoProfile -Command "[Console]::Out.Write('partial'); [Console]::Error.Write('native stderr'); exit 0" }
  function global:codex { & $global:SageNativePowerShell -NoProfile -Command "[Console]::Out.Write('partial'); [Console]::Error.Write('native stderr'); exit 0" }
  function global:agy { & $global:SageNativePowerShell -NoProfile -Command "[Console]::Out.Write('partial'); [Console]::Error.Write('native stderr'); exit 0" }
  function global:grok { & $global:SageNativePowerShell -NoProfile -Command "[Console]::Out.Write('partial'); [Console]::Error.Write('native stderr'); exit 0" }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-stderr') *> $null; $rc = $LASTEXITCODE
  EQ "partial stdout + native stderr 不得算成功 → quorum exit 1" $rc 1
  function global:claude { Write-Output ' '; $global:LASTEXITCODE = 0 }
  function global:codex { Write-Output ' '; $global:LASTEXITCODE = 0 }
  function global:agy { Write-Output ' '; $global:LASTEXITCODE = 0 }
  function global:grok { Write-Output ' '; $global:LASTEXITCODE = 0 }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-empty') *> $null; $rc = $LASTEXITCODE
  EQ "全 reviewer 空白輸出 → quorum fail-closed exit 1" $rc 1
  function global:claude { Write-Output 'only-one-success'; $global:LASTEXITCODE = 0 }
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-one') *> $null; $rc = $LASTEXITCODE
  EQ "僅 1 家成功 → 未達預設 quorum 2 exit 1" $rc 1
  $env:SAGE_MIN_REVIEWERS = '1'
  & "$Scr\crosscheck.ps1" (Join-Path $Tmp 'rev.md') (Join-Path $Tmp 'ccout-badquorum') *> $null; $rc = $LASTEXITCODE
  EQ "非法 quorum <2 → exit 1" $rc 1
  Remove-Item Env:\SAGE_MIN_REVIEWERS -ErrorAction SilentlyContinue

  Remove-Item Function:\global:claude, Function:\global:codex, Function:\global:agy, Function:\global:gemini, Function:\global:grok -ErrorAction SilentlyContinue
  Remove-Item Env:\SAGE_STUB_LOG -ErrorAction SilentlyContinue

  Write-Host ""
  Write-Host "[workflows/sop-run.js]（形態2 語法煙測，有 node 才跑）"
  # 與 bash 側同形：剝 `export const meta` 後包進非 module AsyncFunction、加 "use strict"
  # 前導，只解析不執行。紅=Workflow runtime 會拒啟動（import.meta 類事故，見 0.13.0）。
  $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
  if ($nodeCmd) {
    $sopParse = 'const fs=require("fs");const src=fs.readFileSync(process.argv[1],"utf8").replace(/^export (?=const meta)/m,"");const AF=Object.getPrototypeOf(async function(){}).constructor;new AF("args","budget","agent","parallel","pipeline","phase","log","workflow",`"use strict";\n`+src);'
    & node -e $sopParse (Join-Path $SopDir 'workflows/sop-run.js') 2>$null; $rc = $LASTEXITCODE
    EQ "sop-run.js 以 runtime 同形包裝可解析（AsyncFunction+strict，不執行）" $rc 0
    & node --test (Join-Path $SopDir 'tests/sop-run.test.js') *> $null; $rc = $LASTEXITCODE
    EQ "sop-run.js 語義／quorum／exception 負測全綠" $rc 0
    $badJs = Join-Path $Tmp 'sopjs-bad.js'
    [System.IO.File]::WriteAllText($badJs, "const x = import.meta.url`n")
    & node -e $sopParse $badJs 2>$null; $rc = $LASTEXITCODE
    if ($rc -ne 0) { OK "煙測能抓 module-only 語法（import.meta → 紅）" } else { NG "煙測放行了 import.meta（守門失效）" }
  } else {
    Write-Host "  （無 node → 跳過。形態2 是 opt-in，缺 node 不算失敗）"
  }

  Write-Host ""
  Write-Host "[version/release 機械一致性] (X-05)"
  $verTxt = ([System.IO.File]::ReadAllText((Join-Path $SopDir 'VERSION'))).Trim()
  $clMatch = Select-String -Path (Join-Path $SopDir 'CHANGELOG.md') -Pattern '^## \[(\d+\.\d+\.\d+)\]' | Select-Object -First 1
  $clVer = if ($clMatch) { $clMatch.Matches[0].Groups[1].Value } else { '(無)' }
  EQ "VERSION == CHANGELOG 最新條目（$verTxt）" $verTxt $clVer
  $sverTxt = ([System.IO.File]::ReadAllText((Join-Path $SopDir 'SOP_VERSION'))).Trim()
  $sclMatch = Select-String -Path (Join-Path $SopDir 'SOP_CHANGELOG.md') -Pattern '^## \[(\d+\.\d+\.\d+)\]' | Select-Object -First 1
  $sclVer = if ($sclMatch) { $sclMatch.Matches[0].Groups[1].Value } else { '(無)' }
  EQ "SOP_VERSION == SOP_CHANGELOG 首條（凍結快照 $sverTxt）" $sverTxt $sclVer
}
catch {
  # 終止性錯誤不得靜默跳過剩餘案例還報全綠——自檢自己必須 fail-closed
  NG "selftest 執行中斷（terminating error）：$($_.Exception.Message)"
}
finally {
  Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "═══ 自检結果：$pass 通過 / $fail 失敗 ═══"
if ($fail -eq 0) { Write-Host "✓ 本機 .ps1 腳本工作正常"; exit 0 }
else { Write-Host "✗ 有失敗項，請檢查上面 ✗ 條目"; exit 1 }

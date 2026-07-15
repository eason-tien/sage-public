<!-- AGENT-FACING. 程式面審計記錄（2026-07-13）。ROADMAP.md 的迭代項引用本檔 ID；修掉一條就在對應迭代的 CHANGELOG 勾銷，MUST NOT 改寫本檔的發現原文。 -->
# AUDIT 2026-07-13 — 程式面全量審計（v0.8.1 基線）

METHOD: 5 個獨立審查維度（bash / PowerShell / 編排器+hook / 文件漂移 / 工程缺口）並行精讀 + 每條發現由獨立對抗式驗證者親讀程式碼、可實測者實測復現後裁定。
RESULT: **45 條確認**（P0×3 / P1×18 / P2×24）、3 條駁回、16 條未驗證候補（超出每維度 10 條驗證上限，僅列存目）。
BASELINE: commit cbcb7ea（v0.8.1）。所有行號以該基線為準。

ID 規則：B=bash W=PowerShell O=編排器/hook D=文件漂移 X=工程缺口。跨維度同根因互相標註（如 W-02≈B-01）。
嚴重度：P0=照文檔正常使用即產生假綠（信任錨失效） · P1=重要缺口/明確違反自家鐵律 · P2=不一致/健壯性 · P3=次要。

## B — bash 腳本

### B-01 [P0] `scripts/verify.sh:66`
verify.sh 用 eval 在當前 shell 執行驗收行，官方範例中的 exit 會讓 verify 提前退出 0 並跳過其餘驗收（fail-open，破 R9）
- 修法：把執行改為隔離子進程：`if ( eval "$cmd" ) >>"$LOG" 2>&1 </dev/null; then` 或 `bash -c "$cmd"`（後者順帶解決 set 選項洩漏）。同步在 selftest.sh 加一條案例：acceptance 檔第一行 `exit 0`、第二行 `false`，期望 verify exit 1。verify.ps1 需檢查是否有等價問題。此修法不加任何抽象層，符合 KEEP-THIN。

### B-02 [P1] `scripts/verify.sh:66`
驗收行與 verify 共用執行環境：一行 `fail=0` 即可洗綠計數器，`cd` 副作用殘留還會把證據日誌劈到別的目錄
- 修法：同 P0 條的修法（子 shell / bash -c）一次解決：子進程中賦值、cd 都不會回滲。建議 LOG 在腳本開頭轉絕對路徑（`LOG="$PWD/verify-..."`），使證據檔位置不受驗收命令影響。

### B-03 [P1] `scripts/verify.sh:58`
verify.sh 的 read 迴圈靜默跳過無換行結尾的最後一行——最後一條驗收命令可能根本沒跑就報綠
- 修法：改為 `while IFS= read -r cmd || [[ -n "$cmd" ]]; do`（bash 慣用法，一行修復）。selftest.sh 加案例：無尾換行的失敗行必須被計為不通過。

### B-04 [P1] `scripts/verify.sh:80`
0 條驗收命令仍判「✓ 全綠」exit 0——new-task 生成的純註解骨架 lock 後直接可認證
- 修法：在摘要後加：`if [[ $n -eq 0 ]]; then echo "✗ 0 條驗收命令——空驗收集不認證"; exit 2; fi`（放在 fail 判斷之前）。selftest 加對應案例（純註解檔 → 非 0）。

### B-05 [P1] `scripts/acceptance-lock.sh:16`
acceptance-lock.sh 在 sha256sum 缺失時（如 macOS 原生環境）lock 仍 exit 0，寫出空 hash 的壞鎖
- 修法：hash 計算後立即驗證：`[[ -n "$hash" ]] || { echo "✗ 無法計算 sha256（缺 sha256sum?）"; exit 1; }`；或加一行 fallback `command -v sha256sum >/dev/null || sha256sum(){ shasum -a 256 "$@"; }`。兩者都只有 1-2 行，不違背 KEEP-THIN。

### B-06 [P2] `scripts/verify.sh:42`
verify.sh 把 acceptance-lock.sh 的任何執行失敗（含腳本不存在 exit 127）一律誤診為「ACCEPTANCE TAMPERED」
- 修法：區分退出碼：`rc=$?; if [[ $rc -eq 127 || ... ]]` 或至少不丟 stderr（把子腳本輸出 tee 進 $LOG），訊息區分「鎖校驗失敗」與「校驗工具不可用」兩種情況，兩者都維持 exit 2。

### B-07 [P2] `scripts/verify.sh:7`
verify.sh 的 set -u/pipefail 洩漏進 eval 的驗收命令，驗收語義與人手跑不一致，SIGPIPE 場景還可能反向洗綠
- 修法：改用 `bash -c "$cmd"` 在乾淨子進程執行（不繼承 -u/pipefail），與 P0 條的隔離修復合併為同一改動；DESIGN.md「verify.* 用退出碼判定」節補一句執行語義說明。

### B-08 [P2] `scripts/verify.sh:16`
SAGE_ALLOW_UNLOCKED 環境變數可無痕降級 R9 fail-closed，訊息還謊稱「顯式」
- 修法：首選：刪掉 env 通道，只認命令列旗標（R5 本來就要求人親自敲命令）。若要保留（CI 場景），訊息必須區分來源：「經環境變數 SAGE_ALLOW_UNLOCKED 跳過（非命令列顯式）」，讓 log 證據如實。

### B-09 [P2] `scripts/verify.sh:58`
CRLF 的 acceptance.txt：lock/check 歸一化通過，verify 卻每條 127 command not found——兩腳本行為不一致
- 修法：read 之後加一行 `cmd="${cmd%$'\r'}"`，與 lock 的歸一化語義對齊。selftest 加 CRLF 案例。

### B-10 [P2] `scripts/preflight.sh:60`
preflight.sh 永遠 exit 0，自身違反本專案 R1「退出碼機械判定」哲學
- 修法：結尾改為 `[[ $warn -eq 0 ]]` 決定退出碼：warn>0 → exit 1（訊息照舊）。selftest.sh 目前只 grep 輸出字串（selftest.sh:61-62），順帶補退出碼斷言。

## W — PowerShell 腳本 / dispatcher

### W-01 [P0] `scripts/verify.ps1:84`
verify.ps1 對「無退出碼的 cmdlet 布林結果」判通過——Test-Path 缺檔也認證全綠（假綠）
- 修法：在判定鏈的 $null 退出碼分支加一條：若管線輸出含 [bool]$false（$out 本身或最後一個元素為 $false）判不通過；同時在 verify.ps1 頭部註解與 new-task.ps1 的 acceptance.txt 模板明示「布林 cmdlet（Test-Path/字串比較）之 False 會判失敗」。約 3 行改動，符合 KEEP-THIN。

### W-02 [P0] `scripts/verify.sh:66` ≈ B-01（同根因，加 .ps1 面）
驗收行含 exit 會提早終結 verify 並以 exit 0 假綠收場（.sh/.ps1 皆中招，且是 verify.sh 自己示範的寫法）
- 修法：bash 改為子 shell 隔離：`if ( eval "$cmd" ) >>"$LOG" ...`（加一對括號即可，exit 只終結子 shell 且退出碼語義不變）。PS 側 scriptblock 無法隔離 exit：或改子行程執行每行（powershell/pwsh -NoProfile -Command $cmd，以 $LASTEXITCODE 判定），或至少在 verify.ps1 註解與模板明文禁止裸 exit 行。兩邊模板/用法說明同步改掉危險範例。

### W-03 [P1] `scripts/acceptance-lock.ps1:14`
acceptance-lock 雜湊演算法 .ps1/.sh 不等價：BOM、孤立 CR、重新編碼造成跨實作 .lock 互判 TAMPERED
- 修法：PS 版 Get-NormHash 改成位元組級與 bash 完全一致：`[System.IO.File]::ReadAllBytes($p)` 過濾 0x0D 後直接 SHA256，不做任何文字解碼/再編碼。一次性遷移成本：既有 .lock 需 relock（本來就有顯式 relock 流程可走）。

### W-04 [P1] `sage.ps1:16`
sage.ps1 dispatcher：$Rest 為 $null 時 @Rest splat 塞入一個 $null 位置參數——sage lock/relock/check/verify 不帶檔名全數壞掉；switch 參數無法轉發
- 修法：在 switch 前加 `if ($null -eq $Rest) { $Rest = @() }`（一行修復所有預設檔名子命令）；-AllowUnlocked 轉發：dispatcher 在 verify 分支偵測字串 '-AllowUnlocked'/'--allow-unlocked' 並改為顯式 `& verify.ps1 @files -AllowUnlocked`，或與 verify.ps1 補 SAGE_ALLOW_UNLOCKED 環境變數（見另條）一起解。

### W-05 [P2] `scripts/crosscheck.ps1:63`
crosscheck.ps1：switch 未定義的 reviewer 或非原生 CLI 失敗時仍回報「✓ 完成」（bash 版回 127 判失敗）
- 修法：default 分支加 `$global:LASTEXITCODE = 127`；並在成功判定中同時檢查輸出檔非空（`(Get-Item $out).Length -gt 0`）以涵蓋非原生 CLI 不設退出碼的情形。

### W-06 [P2] `scripts/preflight.ps1:42`
preflight.ps1 吃到殘留 $LASTEXITCODE：git 根本沒安裝仍印出「✓ 工作區乾淨（適合開始 /goal）」
- 修法：沿用 crosscheck.ps1 已有的 preset 手法：每次 git 探測前先 `$global:LASTEXITCODE = 1`（L16 與 L42 兩處），或以 `if (Test-Cmd git)` 守住 [4] 整段。

### W-07 [P2] `scripts/crosscheck.ps1:64`
crosscheck.ps1 用 `1> $out` 重定向寫 review 檔——在主環境 PS5.1 會產出 UTF-16LE(BOM) 的 .md，與 bash 版及自身 skip 路徑不一致
- 修法：改為 `$text = Invoke-Reviewer $label $promptText 2> $err | Out-String; Write-Utf8NoBom $out $text`，與腳本其餘輸出統一 UTF-8 無 BOM；.err 同理。

### W-08 [P2] `scripts/verify.ps1:6`
verify.ps1 缺 SAGE_ALLOW_UNLOCKED 環境變數支援——同一輸入 bash exit 0、PS exit 2
- 修法：param 區後加一行：`if ($env:SAGE_ALLOW_UNLOCKED -eq '1') { $AllowUnlocked = $true }`。順帶解掉 sage dispatcher 無法傳 switch 的痛點（sage verify 前先設環境變數即可）。

### W-09 [P2] `scripts/new-task.ps1:107`
new-task.ps1 在 git init/commit 全失敗（如無 git）時仍印「✓ 任務已建立」並 exit 0；bash 版 set -e 以 127 中止
- 修法：開頭加 `if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host '✗ 找不到 git'; exit 1 }`；L107 改為警告後 `exit 1`（或至少非零），對齊 bash 的失敗語義。

### W-10 [P2] `sage.ps1:24`
sage rules 用無 -Encoding 的 Get-Content 讀 UTF-8 無 BOM 的 AGENTS.md——在自家宣告的主環境（中文 PS5.1）輸出亂碼
- 修法：改為 `Get-Content -Encoding UTF8 (Join-Path $script:SopRoot 'AGENTS.md')`（參數本身是 ASCII，不違反 sage.ps1「ASCII-only」前提）。

## O — 形態2 編排器與 hook 層

### O-01 [P1] `workflows/sop-run.js:20`
sop-run.js 硬編碼作者個人機器的 REPO 絕對路徑，換機後所有子 agent 讀不到規則與 prompts
- 修法：把 REPO 改成 `A.repo ||`（args 傳入），未提供時不要 fallback 到個人路徑，而是 log 明確警告並 early return（腳本已有 top-level return 能力，見 175 行）；或在 RULES 中改為指示 agent 以 scriptPath 所在目錄向上定位 AGENTS.md。改動一行 + 一個 arg，不違背 KEEP-THIN。

### O-02 [P1] `workflows/sop-run.js:40`
無 spec 時宣稱的「hard-stop」不可能成立：PLAN_SCHEMA 強制 agent 捏造結構化輸出，且流程照跑四個 phase
- 修法：在 A 解析完後加一個 guard：`if (!SPEC && !SPEC_FILE) return { error: 'no spec; fill prompts/01-spec.md first', humanGate:{...} }`，在編排層機械地擋，而不是叮囑 agent 自己停。若要保留 agent 側判斷，給各 schema 加可選 `hardStop:{reason}` 逃生欄位並在腳本檢查後短路。

### O-03 [P1] `workflows/sop-run.js:132`
子 agent 失敗無任何防護：plan 為 null 時把字串 "null" 當計畫發給 reviewer；全體 reviewer 失敗仍產出「匯總決策包」
- 修法：plan/agg/goal 各加 falsy guard：失敗即 early return {error, phase}；回傳物件加 reviewersRequested 與 reviewersCompleted 兩個數字；reviews.length===0 時直接停止並回報，不進 Aggregate。約 6 行改動。

### O-04 [P1] `HOOKS.md:27`
HOOKS.md 宣稱 exit 2 會「把信息回灌给 agent」，但 acceptance-lock 的輸出全走 stdout——agent 被擋卻收不到原因
- 修法：文件中的命令改為把 check 輸出導到 stderr：bash 版 `bash …/acceptance-lock.sh check acceptance.txt 1>&2 || exit 2`；PowerShell 版在包裝裡捕獲輸出後 `[Console]::Error.WriteLine($out)` 再 exit 2。並修正第 27 行敘述為「stderr 回灌」。

### O-05 [P2] `workflows/sop-run.js:45`
RULES 叫 agent 去 README.md 讀「R1-R8 iron rules」——R9 缺席、且 README 已不含鐵律正文（canonical 已搬到 AGENTS.md）
- 修法：RULES 改為指向 `${REPO}/AGENTS.md`（單一事實源），文案改 R1-R9，並在 HARD LIMITS 補一條 R9（驗收集鎖定、relock 屬人類動作）。

### O-06 [P2] `workflows/sop-run.js:3`
「絕不做不可逆操作」只是 prompt 級叮囑：agent() 調用未附任何工具限制，與本包「不信叮囑、要機制」的哲學不一致
- 修法：二擇一：(a) 若 Workflow 的 agent() 支援工具白名單/唯讀選項，在四處調用加上（機制化保證）；(b) 若不支援，在 sop-run.js 檔頭與 workflows/README.md「它绝不做」段補一行誠實標註：此邊界為 prompt 級約束（同 R9 的 tamper-evident 措辭），最終仍靠人審 humanGate。

### O-07 [P2] `workflows/sop-run.js:32`
reviewers 參數無上限也無驗證，編排器自身不守 R4（token 上限 + max turns + 輸出導日誌）
- 修法：`const N_REV = Math.min(Math.max(parseInt(A.reviewers,10)||3,1),4)`，clamp 時 log 警告；若 agent() 支援 maxTurns/token 選項則對每個子 agent 傳入固定上限。兩行改動。

### O-08 [P2] `scripts/selftest.sh:2`
sop-run.js 完全在 selftest 覆蓋之外，且其依賴的 Workflow harness 契約（全域變數、top-level return、args 為 JSON 字串）沒有任何機械驗證
- 修法：在 selftest.{sh,ps1} 加一個最薄的 harness 樁：node 裡用 `new AsyncFunction('args','log','phase','agent','parallel', body)`（body=去掉 export 行的檔案內容）注入 stub agent（回傳符合各 schema 的假物件），跑一遍驗證回傳物件含 task/route/plan/reviews/agg/goal/humanGate 七鍵、以及無 spec 時 early-stop 行為。約 30 行，不引入框架。

### O-09 [P2] `HOOKS.md:9`
缺 hook 安裝/卸載工具：HOOKS.md 要求手改 .claude/settings.json，sage 命令也沒有 hook 子命令
- 修法：加 `sage hook install|uninstall|status [任務目錄]`（對應薄腳本 scripts/hook-install.{ps1,sh}）：讀取既有 settings.json、merge 而非覆蓋 hooks.Stop、以 $PSScriptRoot/腳本所在路徑自動填絕對路徑、uninstall 只移除自己那條。維持薄：單檔、無依賴。

## D — 文件漂移

### D-01 [P1] `prompts/01-spec.md:1`
01-spec 模板叫 agent 去 README 找「R1–R8」鐵律——R9 缺席且 README 已不含 R 定義
- 修法：把該行改為「鐵律見 AGENTS.md R1–R9」。同時 grep 全倉「R1–R8/R1-R8」把殘留一次清完（另兩處見 sop-run.js 與 DESIGN.md 的 finding）。

### D-02 [P1] `workflows/sop-run.js:44` ≈ O-05（同一接地錯誤）
sop-run.js 編排器把 reviewer/agent 接地到「README (R1-R8 iron rules)」——R9 完全沒進形態2 的規則面
- 修法：RULES 改指 ${REPO}/AGENTS.md（R1–R9 canonical），並在 HARD LIMITS 補一行 R9（goal 草案的驗收條件須假設 acceptance.txt 會被 lock，verify 無鎖即 exit 2）。

### D-03 [P1] `artifacts-example/EXAMPLE-mes-comm.md:58`
artifacts-example 的最終驗收示範照做會 exit 2：範例沒有 acceptance-lock 步驟，但 verify 已 fail-closed
- 修法：§6 的 bash 區塊在 verify 前補兩行：「./acceptance-lock.sh lock acceptance.txt」與「git add acceptance.txt.lock && git commit」，並在 §5 GATE 清單或 §6 說明中標注 R9。

### D-04 [P1] `scripts/verify.sh:16` ≈ B-08 + W-08（同一後門的文件/等價面）
verify.sh 藏了未文件化的 SAGE_ALLOW_UNLOCKED 環境變數後門，可無痕跳過 R9 fail-closed，且 .ps1 無對應（雙版本不等價）
- 修法：首選直接刪掉這行（KEEP-THIN、與「需顯式動作」的 0.8.0 承諾一致）；若要保留（CI 場景），須：文件化於 README/CHANGELOG、verify.ps1 加同名 env 支援、日誌明示「經 SAGE_ALLOW_UNLOCKED 環境變數跳過」。

### D-05 [P2] `README.md:13`
「快車道」範圍三處說法互相矛盾：README 含 STEP 8（/goal 條件+六道閘），AGENTS/DESIGN/new-task 都說三步收工
- 修法：擇一為準並同步：建議 AGENTS.md（單一事實源）明寫「快車道 = STEP 0,1,2,12；若用 /goal 才加 STEP 8」，README ENTRY 表與 new-task.* 輸出照改，或 README 把 STEP 8 檔位改「用 /goal 時」。

### D-06 [P2] `README.md:51`
README 13 步 STEP 地圖沒有任何 acceptance-lock 步驟，與 AGENTS.md 应用步骤第 4 步矛盾；照地圖走到 STEP 12 直接 exit 2
- 修法：STEP 表在 8 與 9 之間插入「8.5/鎖定驗收集 | acceptance-lock.* lock + commit .lock | 核」（或直接在 STEP 8 行加註），使地圖與 AGENTS.md 六步應用順序一致。

### D-07 [P2] `dogfood/RUN-2026-06-18.md:29`
dogfood 記錄引用的鎖檔內容與實際 committed .lock 不符，且「16 条机械检查/16/0」已過時（現為 20 條）
- 修法：保留歷史原文，但在檔頭或各引文處加「v0.8.0 後現況」註記（lock 引文改抄 committed 內容；16→20 條並注明含 preflight/C1/C2）；或重跑一次 dogfood 出 RUN-v0.8.1 新檔。

### D-08 [P2] `workflows/sop-run.js:20` ≈ O-01（同一硬編碼路徑）
sop-run.js 硬編碼個人 Windows 絕對路徑當 REPO，與 workflows/README 的 <repo> 可攜寫法矛盾
- 修法：sop-run.js 改為必填 args.repo（缺省時 log 警告並 hard-stop，同 spec 缺失的處理）或由 scriptPath 推導；HOOKS.md 範例路徑改「<本包路徑>/scripts/acceptance-lock.ps1」佔位符。

### D-09 [P2] `DESIGN.md:46`
DESIGN.md SELFTEST 段仍寫「跑四腳本」，實際 selftest 測五個腳本
- 修法：「四腳本」改「五腳本」，並列名（new-task/verify/acceptance-lock/preflight/crosscheck）防下次再加腳本時只改數字。

## X — 工程基礎設施缺口

### X-01 [P1] `DESIGN.md:46`
全 repo 無任何 CI（沒有 .github/workflows），selftest 只靠「換機先跑」的自律——與 R1 機械驗收哲學自相矛盾
- 修法：加一個最薄的 .github/workflows/selftest.yml：兩個 job——ubuntu-latest 跑 `bash scripts/selftest.sh`、windows-latest 跑 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/selftest.ps1`，可加 macos-latest 跑 .sh 版（會立即暴露 sha256sum 缺口，見另一條 finding）。這不違背 KEEP-THIN：NON-GOALS 說的「不做自動編排程序」指任務編排（形態2），CI 只是把既有 selftest 的觸發時機從「換機時手動」改成「每 push 自動」，正是 R9「把自律升級為機制」的同一精神；一個 ~20 行 YAML、不引入任何框架或依賴。

### X-02 [P1] `scripts/acceptance-lock.sh:16`
acceptance-lock.sh 依賴 sha256sum，macOS 原生沒有此命令 → 在 AGENTS.md 明列支援的 macOS 上 R9 鎖鏈整條壞掉
- 修法：最薄修法（3 行）：在 acceptance-lock.sh 開頭做一次 fallback——`if command -v sha256sum >/dev/null; then H=sha256sum; else H='shasum -a 256'; fi`，或缺命令時明確報錯 exit 1（比空 hash 誤報 TAMPERED 誠實）。同時 preflight.sh 加一條 `check "sha256 工具可用" ...`。完全不違 KEEP-THIN；若加了 macOS CI job（見 CI finding），此類缺口以後會被機械抓出。

### X-03 [P1] `sage.ps1:2`
只有 sage.ps1 dispatcher，Linux/macOS 使用者沒有等價的 `sage` 命令入口；INSTALL 只寫 PowerShell profile
- 修法：新增 ~40 行的 `sage.sh`：一個 `sage()` shell function + case 分派（new/lock/relock/check/verify/crosscheck/preflight/test/rules/help），與 sage.ps1 的 switch 一一鏡像，零新抽象；README INSTALL 加兩行 bash/zsh 段：`echo 'source <本包路徑>/sage.sh' >> ~/.bashrc`。selftest.sh 加一條煙霧測試（`source sage.sh && sage help` exit 0）。這是 sage.ps1 的對稱補全而非新機制，不違 KEEP-THIN。

### X-04 [P1] `scripts/verify.sh:3`
所有 .sh 腳本在 git 中都是 100644（無執行位），Linux/macOS clone 後照文件敲 `./verify.sh` 直接 Permission denied
- 修法：一條命令修復：`git update-index --chmod=+x scripts/*.sh`（sage.sh 若新增也一併）並 commit。零程式碼、零哲學爭議。可在 selftest.sh 加一條 `[[ -x "$SCR/verify.sh" ]]` 檢查防回歸（Windows 上 git bash 也能讀到 mode）。

### X-05 [P2] `VERSION:1`
VERSION、CHANGELOG、git tag 三者無機械一致性檢查，且 repo 完全沒有 tag——版本只活在 commit message 裡
- 修法：最薄補法兩件事：(1) selftest.{sh,ps1} 各加一條 3 行檢查：`grep -q "^## \[$(cat "$SOP_DIR/VERSION")\]" "$SOP_DIR/CHANGELOG.md"`（PS 版對應 Select-String），讓 VERSION↔CHANGELOG 漂移機械可判；(2) release 流程不寫腳本、只寫一行約定進 CHANGELOG.md 開頭或 README：每次 bump 後 `git tag v$(cat VERSION) && git push --tags`，並回補既有版本的 tags。不加 release 工具鏈、不加 CI 發佈 job，不違 KEEP-THIN。

### X-06 [P2] `DESIGN.md:40`
DESIGN.md 明定的編碼不變量（.sh 必 LF 無 BOM、.ps1 必 UTF-8 BOM）零機械執行；shellcheck/PSScriptAnalyzer 全 repo 無任何蹤跡
- 修法：最薄補法：selftest.{sh,ps1} 加一段 ~8 行編碼檢查——對每個含非 ASCII 的 .ps1 驗前 3 bytes == EF BB BF；對每個 .sh 驗無 BOM 且 `grep -c $'\r'` == 0。shellcheck 不引入本機依賴，只在 CI 的 ubuntu job 加一行 `shellcheck scripts/*.sh`（runner 內建）；PSScriptAnalyzer 同理放 windows job 一行 Invoke-ScriptAnalyzer。守既有不變量而非加新規則，不違 KEEP-THIN。

### X-07 [P2] `HOOKS.md:19`
HOOKS.md 的 Stop-hook 範例硬編作者私人絕對路徑，照抄即壞；clone 之外沒有任何更輕的取得方式
- 修法：HOOKS.md 把範例路徑改為 `<SAGE_ROOT>` 佔位符並加一句「替換為你的本包絕對路徑」，順帶補 HOOKS.md L33 已建議的驗證步驟為明確命令。取得方式不建議做 installer/包管理（違 KEEP-THIN）；最薄做法是打 tag 之後在 README INSTALL 段加一行固定版本取得指令：`git clone --depth 1 --branch v0.8.1 <repo>` 或 release zip 連結。

## 駁回（3 條——記錄下來防止未來迭代重提）
1. **Stop-hook 未處理 stop_hook_active / 無鎖也 exit 2 會鎖死會話** — 駁回。TAMPERED 時 agent 的合規出路是把 acceptance.txt 還原到鎖定版本（git 裡有），hash 復原即通過；「無鎖也擋」是 R9 fail-closed 的明文設計而非疏漏。
2. **dogfood 驗收集是 Windows-only、非 Windows 無法復現** — 駁回。驗收命令天然綁定任務環境（沒裝 pytest 的機器跑 pytest 任務一樣紅）；跨平台鏈路驗證的官方路徑是 selftest（Linux 實測 lock/check/fail-closed 全通）。
3. **DESIGN.md 形態2 註記稱內核為「R1-R8」** — 驗證 agent 中途失敗（API 斷線），按 fail-closed 記駁回；但主迴圈已自行覆核 DESIGN.md:53 確有「內核（P1-P6 / R1-R8）不變」字樣，屬實，已併入 ROADMAP 迭代 4 的 R9 漂移掃除批次。

## 未驗證候補（16 條存目——審查者回報但超出驗證上限，未經對抗式驗證，引用前 MUST 先自行核實）

- [P3] `scripts/crosscheck.sh` — crosscheck.sh：reviewer 失敗時訊息叫人看 .err，空 .err 卻被隨手刪掉；四家全失敗/全未安裝仍 exit 0
- [P3] `scripts/verify.sh` — verify.sh 參數解析：未知 --旗標與多餘位置參數被靜默當成驗收檔名
- [P3] `scripts/selftest.sh` — selftest.sh 對 verify 的 fail-open 面零覆蓋——本次全部 P0/P1 都在 selftest 綠燈下存在
- [P3] `scripts/new-task.sh` — new-task.sh 在 git commit 失敗（如全域 commit.gpgsign=true 無金鑰）時留下半成品目錄，重跑被「目錄已存在」卡死
- [P3] `scripts/selftest.ps1` — selftest.ps1 以 `cmd /c exit N` 當樁命令——pwsh on Linux/macOS 下自檢誤報失敗
- [P3] `scripts/crosscheck.ps1` — crosscheck.ps1 在 prompt 模板缺失時不中止：以「無審查提示詞」的內容呼叫真實 CLI 並回報成功（bash 版 set -e 立即 exit 1）
- [P2] `HOOKS.md` — hook 自身沒有 selftest：HOOKS.md 要求人「裝上後手動用被改過的 acceptance 驗證一次」，與核心哲學直接矛盾
- [P2] `HOOKS.md` — 缺一段 PreToolUse 護鎖片段：R9 自認最大繞道（agent 直接改/刪 .lock）在 hook 層其實封得掉，但 HOOKS.md 只給了 Stop-hook
- [P3] `workflows/sop-run.js` — blockingCount 叫 LLM 去數，而腳本手裡就有全部 findings——違反本包自己的 P2「可機械檢驗」
- [P3] `workflows/sop-run.js` — 雜項健壯性：args 全域缺席會 ReferenceError、humanGate 硬編碼工廠域文案、spec 與 specFile 同給時靜默取捨
- [P3] `HOOKS.md` — HOOKS.md 設定片段結構本身合法可裝，但範例含作者個人絕對路徑、matcher 欄對 Stop 事件多餘
- [P2] `prompts/05-goal.md` — 「HANDOFF 五區塊」兩套枚舉對不上：05-goal/EXAMPLE 的五塊 ≠ HANDOFF.md 模板的五個 required 區塊
- [P3] `scripts/new-task.sh` — new-task 收尾提示指向 README 已不存在的章節，且 .sh 與 .ps1 指的還是兩個不同的舊名
- [P3] `DESIGN.md` — DESIGN 規定「.ps1 MUST UTF-8 with BOM」，但 sage.ps1 與 acceptance-lock.ps1 刻意 ASCII 無 BOM，規則未收錄例外
- [P3] `scripts/new-task.sh` — STEP 13 / final-acceptance 要求寫 lessons.md 復盤，但 new-task.* 不複製也不檢查 lessons 模板
- [P3] `scripts/acceptance-lock.ps1` — acceptance-lock 的 .sh 與 .ps1 寫入的時間戳格式不一致（UTC Z vs 本地帶時區 o 格式），違反雙版本等價宣稱

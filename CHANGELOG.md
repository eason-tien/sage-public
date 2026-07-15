# Changelog

本檔記錄 ai-dev-sop 的版本變更。格式依循 [Keep a Changelog](https://keepachangelog.com/)，
版本號依循 [語意化版本](https://semver.org/lang/zh-TW/)。

## RELEASE 流程（機械化，selftest 看守）
1. 改 `VERSION` + 本檔新增條目（selftest 驗兩者一致 + 連結錨點存在，紅了不能出貨）。
2. commit；`sage version` 輸出必等於 `VERSION`（selftest 已看守）。
3. **合入 master 後**對合入點打 annotated tag 並推送：`git tag -a vX.Y.Z <commit> -m "vX.Y.Z" && git push origin vX.Y.Z`。
   MUST NOT 對未合入分支的 commit 打 tag（rebase/squash 會使 tag 指向孤兒 commit）。
   註：v0.9.0 已存在於遠端（53f21ea）；其餘歷史版本的「版本→commit」對應已按各 commit 的
   `VERSION` 檔內容逐一驗證（見 0.11.0 條目），tag 推送需倉庫管理者執行（agent 開發環境僅能
   推指定分支）。0.2.0/0.3.0 無任何 commit 帶過該版號（0.1.0 直跳 0.4.0），不猜測、不補打。
4. 修**閘門類 bug**（verify/lock/preflight 的判定邏輯）MUST 先在 selftest 寫一條會紅的負向案例，
   親眼看它紅，再修到綠——爛閘洗白信任，比沒有閘更危險。
5. **minor 版本（0.X.0）出貨前 MUST 跑一輪對抗式審查**（多 agent 或換模型審 diff），發現記入條目。

## [0.13.2] - 2026-07-14

### 安全與治理 (Security / Governance)

- **修正 version ledger merge 假綠**：CI 驗證完整 base→head 範圍，從指定 candidate commit
  讀取帳本，不再只看 merge/tip 單一 commit；歷史必須維持前綴、patch 版連續，且所有新增
  records（成功或失敗）都必須具備嚴格 frontmatter、非空 Memory/Task Note 與對應上下文；
  successful records 的 `changed_files` 聯集必須覆蓋整個範圍的專案變更與刪除。pre-commit
  對任何 staged ledger/task-note 直接讀 Git index，未暫存的新版帳本不能替 staged decoy 背書；
  committed 模式只讀指定 commit，不再受 dirty worktree 誘餌影響。最終 successful record
  另以 canonical tree SHA-256 綁定所有版本化路徑、mode 與 Git clean-filter 後的 bytes；worktree
  透過隔離的臨時 index/object DB 計算，與 staged index／commit 在 `eol=crlf` 或自訂 filter 下
  仍位於同一雜湊域，且不改真實 index/object store；ignored governance 目錄不會被誤當顯式
  `git add` 目標，unborn HEAD 的首次 staged record 也能檢驗。完整歷史的 Memory／Ver／Task
  Note 都會重驗。diff 停用 rename detection 並涵蓋 type change，不能再以同名二次篡改、
  regular→symlink 或 rename 進 `reports/` 繞過。
- **建立 fail-closed 本機 merge 入口**：`.github/sage-merge-policy.json` 固定五個 CI jobs；
  `tools/merge_pr.py` 要求所有回報 checks 通過、PR head/base/branch 精確一致、無 draft／
  auto-merge／conflict，並從單一不可變 snapshot 驗證分離的自動 Evidence 與人工 `sage-r5`
  SSH 簽章、實際 signer fingerprint、policy/log/evidence hashes；兩個 trust stores 只要共用 key
  即拒絕。真正 merge 需人類互動輸入完整 PR + SHA，最後以 `--match-head-commit` 綁 head；永不
  使用 `--admin`、`--auto` 或自動刪分支；互動等待後會再次驗證 R5 freshness。此 wrapper
  仍是可被 GitHub 權限繞過的本機控制；
  private repo 的 protection/rulesets API 目前因方案限制回傳 403，server-side enforcement 未完成。
- **提供不升級方案的 history-free public release gate**：保留含 hidden oracle 的完整倉庫為
  private，`tools/public_export.py` 只從一個 immutable source tree 產生兩個 commit 的
  `sage-public` 候選；排除 oracle、private workflow/policy、來源歷史與既有 certificate，並拒絕
  symlink／gitlink、大小寫碰撞、不安全路徑及與 excluded oracle 完全相同的 Git blob。Gitleaks
  通過後，以 SSH certificate 綁 source/public tree、exact-head private attestation 與安全狀態；
  attestation 必須明確包含兩個 private oracle gates 與 private-tree version-ledger gate，公開 CI
  不會拿私有 candidate-tree digest 錯比已移除 oracle 的公開 tree；
  公開 `pull_request_target` oracle 永遠使用 base 的 trusted verifier，只把 candidate 當資料，
  再由 public branch protection 要求 oracle 與五個 CI checks。任何 automation 仍不得宣告 R5 或
  merge authorization。
- **PR #7–#10 逆向追溯**：固化 base/head/merge SHA、Actions run 與 review 時序。四個 PR
  都在 `test` 失敗時合併，且沒有 APPROVED/R5 證據；歷史只記 `merge_observed=true`，不得改寫成
  `r5_human_verification=passed` 或 `merge_authorized=true`。

### 修復 (Fixed)

- **runner stage／baseline／empty patch 假成功**：clone 必須等於 source head；所有 diff 與 gates
  鎖定初始 baseline；stage 非零或移動 HEAD 立即失敗但保留完整 raw output/metadata；空 candidate
  不能通過 final gates、升 knowledge 版本或簽 Evidence。另鎖定 critical Git metadata，拒絕
  index flags／index.lock／replace refs／ignored hidden files／metadata drift，`git add -N` 非零立即
  失敗。最終 gates 與 post-implementation attestation 都從 baseline 在全新 clone 重建 exact
  binary patch 後執行，移除 candidate clone 的 source remote，並在 CodeGraph、acceptance、quality
  gate 與 gitleaks 前拒絕 absolute／
  解析後越出 candidate root 的 symlink；因此 ignored `.codegraph` payload、未物化 gitlink 內容
  或 workspace 外部 symlink 不能替可攜 patch 背書；真實 staged index 變更也不再從 worktree
  diff 消失。Acceptance、quality/plugin gate 與 Promotion replay 子行程另使用 credential-minimized
  environment，不繼承 provider／CI token。
  這些是靜態／環境收斂，不是 hostile runtime sandbox；簽署 result 會明列 filesystem/network
  sandbox 均為 false，高信任無人值守仍必須把整個 runner 放進外部 container／VM。attestation 使用
  獨立 execution kind、無虛構 agent stage，並涵蓋刪除檔與新增檔；attestation 在重建後先用
  intent-to-add 將新增路徑納入 exact patch 比對，不能因 raw `git diff` 忽略 untracked 新檔而
  假報 materialization mismatch 或漏簽候選內容。
- **crosscheck quorum**：預設至少兩個 reviewer command 存在、exit 0、stderr 空且 stdout 非空才算
  成功；PowerShell 的 null `$LASTEXITCODE`、pipeline/ErrorRecord 失敗與 partial output 全部紅燈；
  每家使用獨立臨時 cwd，所有 reviewer 結束前不發布任何 review；重用 output dir 會先清除腳本
  管理的舊 review/failed/status 產物，避免跨 run 混票；PowerShell 的待審輸入必須是可讀 leaf，
  暫存、集中發布或 cleanup 任一步 I/O 失敗都不得宣告 quorum。這是流程層隔離，不宣稱是惡意
  CLI 的 OS sandbox。
- **SOP 形態2 fail-closed**：新增 content-addressed `sop-preflight.py` bundle，驗證規則／設計／
  prompts／spec／共享 `SAGE_KNOWLEDGE.md`／CodeGraph；`sop-run.js` runtime 重算內容 SHA-256、
  綁 40-hex source HEAD、15 分鐘時效與 Stitch/spec 一致性，強制 2–4 reviewers、動態 quorum、
  plan/review/aggregate/goal 語義、`GATE-5.autoSatisfiable=false` 與明確人工 R5；Stitch 分類同時
  辨識 action-before-target 與 `Desktop UI design` 這類 target-before-action 語序；純治理規則
  文字不會誤觸發，同份 spec／同一行的 policy words 也不能壓掉真正 UI 實作，並涵蓋
  `update`／`restyle`／`rework` 視覺動作。bundle 未簽章，
  所以來源真實性仍以 trusted launcher 為邊界，不宣稱 cryptographic attestation。
- **acceptance lock pipeline**：在 `pipefail` 下明確檢查整段 CRLF→LF（保留 lone CR）→SHA pipeline，
  避免上游 normalize 失敗卻被下游合法 digest 洗綠；lone CR 改變 PowerShell 執行分行時必須觸發
  TAMPERED，EOF lone CR 也跨 Bash／PowerShell 使用相同 byte-level hash；timestamp 或 lock 寫入
  失敗必須非零；`verify` 先 snapshot acceptance 與 lock，再以同一份 bytes 校驗及執行，避免
  check 後換檔的 TOCTOU；PowerShell 建立或追加驗收證據日誌失敗一律 exit 2，不得在缺證據時
  宣告全綠。C locale 與 invalid UTF-8 回歸案例亦看守。
- **Evidence 簽章 TOCTOU**：result／patch／budget 從單一 regular-file bytes snapshot 驗證與雜湊；
  manifest 直接由 stdin 交給 `ssh-keygen` 簽 exact in-memory bytes、自驗實際 fingerprint 後原子發布，
  verifier 再把 run identity、acceptance 與 changed-file scope 交叉對回 `result.json`。
- **Claude Stop hook 無限循環**：新增 `scripts/claude-stop-hook.py`，驗證官方 Stop stdin contract
  與 `stop_hook_active`。第一次鎖失敗 exit 2 回饋 agent；重試仍失敗改為 `continue:false` 升級人工，
  NUL／過長／無權限路徑與解析例外也以 exit 0 JSON 安全升級，始終維持 R5 pending／merge unauthorized。

### 文件與驗證 (Documentation / Verification)

- README、HOOKS、SOP README、fail-closed merge 操作手冊、history-free public release 手冊與
  `reports/governance-recovery-v0.13.2.md` 對齊實際邊界。
- 新增 Python、Node、Bash、PowerShell 正反向測試，涵蓋 merge commits、多 commit ledger、
  candidate snapshot、stage exit/moved HEAD、empty candidate、review quorum、SOP bundle/semantics、
  Stop recursion、Git metadata／ignored／gitlink 隱藏變更、tree-bound ledger、attestation→SSH
  sign→verify、簽章 TOCTOU、同 key 隔離、SSH R5 簽章、freshness 重驗與篡改拒絕。

## [0.13.1] - 2026-07-14

### 修復 (Fixed) — 形態2 O-03 第四隻 agent（PR #9 審查 Codex P2；合入後補丁）
- **goal-draft 回 null 形似完工**：schema 失敗/超時/取消時照樣返回「Pre-execution complete」
  包裹——`goal:null`、無 hardStop，humanGate 卻請人確認一份從未起草的 gateChecklist。
  補上與 plan/aggregate 同款守門：即停返回 `{hardStop:'GOAL_FAILED'}`，已產出的
  plan/reviews/agg/blockingCount 隨包附上。四隻 agent（plan/reviewer/aggregate/goal-draft）
  的 O-03 亡靈防護至此對齊；workflows/README hardStop 清單同步。

## [0.13.0] - 2026-07-14

### 修復 (Fixed) — 迭代 5：形態2 編排器與 hook 層修繕（opt-in 層；AUDIT O-01…O-08）
- **[P0] sop-run.js 根本起不來（O-01 演變）**：上游改用 `import.meta.url` 自推根路徑，但
  Workflow runtime 把腳本包進**非 module** async 函式——`import.meta` 是啟動前 SyntaxError，
  真 runtime 實測拒啟動。回到 ROADMAP 5.1 原案精神（根路徑必填參數；表中原寫 `args.repo`，
  實作沿用既有參數名 `args.sageRoot`，就是 scriptPath 裡同一個 `<repo>`），缺 → 零 agent
  返回 `{hardStop:'NO_SAGE_ROOT'}`（agent 的規則接地全靠這個根，沒根就跑等於悄悄丟掉
  R1–R9 接地——fail-closed）。
- **無 spec 假跑（O-02）**：舊版只 log 警告叫 agent「hard-stop」，但 structured-output schema
  強制其捏造 plan 照跑四 phase。現在 Plan 前早退：零 agent、返回 `{hardStop:'NO_SPEC'}`。
  真 runtime 兩次冒煙實測 `agent_count=0`（NO_SAGE_ROOT／NO_SPEC 各一）。
- **agent 亡靈防護（O-03）**：plan agent 回 null → 即停（否則字串 "null" 被序列化進所有
  reviewer 提示照樣「成功」）；reviewer 全滅 → 拒絕彙總（不把空結果包裝成「審過了」）；
  aggregate 回 null → 即停附 plan/reviews/blockingCount（審查補抓：否則 /goal 對著 "null"
  起草、跑完像成功）；reviewer 部分陣亡 → log 警告＋返回 `reviewersRequested/Succeeded`
  兩數字（覆蓋不全必須看得見）。
- **不存在的 agentType（實測新發現，AUDIT 無此條）**：移除 `analyst`/`critic`（預設註冊表
  無此類型，乾淨機器上每個 agent() 都會失敗）；用預設 workflow subagent。
- **reviewers clamp 整數 1..4（O-07）**：只有 4 個獨立視角；非法/0/負數/非數值 → 預設 3、
  小數截斷；預設 3 固定跳過第 4 視角（假設風險）——log 明言、README 記載，要全覆蓋傳 4。
- **blockingCount 程式計數（5.6）**：腳本手裡就有全部 findings，高-severity 計數不再交給
  LLM 數（自家 P2）；agg 的 LLM 計數被程式值覆蓋；對畸形 findings 免疫（非陣列計 0、
  null 元素跳過不炸）。
- **HOOKS.md exit-2 盲攔（O-04）**：Claude Code 對 exit 2 只回灌 **stderr**，原範例輸出全走
  stdout——agent 被擋卻看不到 TAMPERED 原因。兩平台範例改為捕獲輸出→轉寫 stderr→exit 2，
  並明文解釋這條管道；settings.json 轉義注記補上。PS 側必須 **`*>&1`** 而非 `2>&1`：
  acceptance-lock.ps1 診斷走 `Write-Host`（資訊流 6），`2>&1` 抓不到、照樣盲攔（審查抓出）。
- **args 健壯化**：`typeof args === 'undefined'` 守門＋只信任非 null 物件（`args:"null"` 經
  JSON.parse 後首個屬性存取即炸——審查實證）；spec/specFile/task 限字串並 trim（空白 spec
  不再溜過 NO_SPEC 閘、非字串不再以 `[object Object]` 進提示詞）。

### 新增 (Added)
- **selftest.{sh,ps1} 形態2 語法煙測（O-08；5.5 落地形式修正）**：原計畫 `node --check`
  （ESM）與真 runtime 語義恰好相反（ESM 允許 import.meta、禁 top-level return）——改為
  「同形 AsyncFunction 包裝＋"use strict" 前導、只剝 `export const meta`、只解析不執行」
  ＋ import.meta 負向自證案例（守門紅得出來），bash/PS 兩側對稱；無 node 明言跳過
  （形態2 是 opt-in，不因缺 node 打紅）；CI 三平台（ubuntu/macos/windows）經 selftest 覆蓋。
- **O-06 邊界明文（不加機制）**：sop-run.js 頭注＋workflows/README「誠實聲明」——「只起草、
  不做不可逆操作」是提示詞層紀律，harness 未收走子 agent 工具；機械閘在 verify/lock。

### 出貨前對抗式審查（RELEASE 規則 5：3 視角背靠背——JS runtime 語義／shell·PS·JSON 機械
面／文件真實性；逐項實證覆核，發現全數出貨前修畢）
- **[blocker] HOOKS PS 範例 `2>&1` 抓不到 Write-Host**：acceptance-lock.ps1 全部診斷走資訊流
  （6），`$o` 恆空——「修好」的範例仍然盲攔，且文件宣稱與事實不符 → 改 `*>&1`（合併流 2–6，
  PS 5.0+）＋文件明注。其餘軸實證乾淨：JSON 轉義、cmd.exe 不改寫引號內 `>&|;`、缺 .ps1 時
  `$LASTEXITCODE=$null → -ne 0` fail-closed、bash 變體實跑 TAMPERED→stderr→exit 2。
- **[中] `args:"null"` 崩潰**：JSON.parse 得 null 後首個屬性存取 TypeError，整個 workflow
  亡於非受控錯誤而非優雅 hard-stop（其它畸形值都能降級，唯獨 "null" 炸）→ 只信任非 null 物件。
- **[中] 空白 spec 溜過 NO_SPEC**：`spec:" "` 為 truthy，四 phase 照跑、agent 對空規格起草
  ——正是 O-02 宣稱關閉的路 → spec/specFile/task 限字串＋trim。
- **[中] aggregate 亡靈未防**：O-03 原則漏了第三隻 agent——agg null 時 /goal 對字串 "null"
  起草、返回無 hardStop 標記形似成功 → AGG_FAILED 早退附 plan/reviews/blockingCount。
- **[中] reviewer 部分陣亡靜默**：4 個死 3 個照樣「成功」，無任何信號 → log 警告＋返回
  requested/succeeded 計數。
- **[中] O-08 誤引**：agentType 修復原掛 O-08，實則 AUDIT 無此條（O-08 是 selftest 覆蓋缺失）
  → 改標「實測新發現」，O-08 只留給煙測條目；「CI 三平台」原僅 bash 側為真 → 補 PS 側煙測
  使其為真（O-08 修法本就要求 selftest.{sh,ps1} 雙側）。
- **[低] 批**：clamp 收整數（0/小數語義釘死）＋預設 3 固定跳過第 4 視角明文化；
  `sageRoot:"/"` 被削成空的邊角（保 `/`）；blockingCount 對畸形 findings 免疫；煙測剝
  export 收窄到 `export const meta`＋strict 前導（嚴格性未實測，寧誤紅不漏放）＋紅診斷
  改抓 Error 行；ROADMAP/CHANGELOG 措辭與事實對齊（`args.repo`→`sageRoot` 沿革、X-07
  可攜寫法係上游先行落地）；docs/sage-0.9-delivery.md 舊文「import.meta 推導 root」加
  現況註記防復發。

## [0.12.1] - 2026-07-14

### 修復 (Fixed) — macOS（bash 3.2）相容性（PR #7 CI 三平台首驗抓出）
- **`$VAR` 緊貼非 ASCII 字元在 macOS 系統 bash 3.2 會把多位元組吃進變數名 → `set -u` 下
  unbound variable 崩潰**：retro.sh 的骨架 heredoc（`$TASK_NAME（`）在 macOS 產出空內容檔並
  exit 1、selftest.sh 自身在 `（rc=$rc）` 處中斷。全部 bash 腳本掃描後統一改 `${VAR}` 大括號形
  （含上游既有的四處同類潛伏：new-task.sh/crosscheck.sh/verify.sh）；生成物位元組不變。
- **selftest 新增類別看守（先紅後修）**：C locale `[:print:]` 可攜寫法掃全部 .sh，`$VAR` 緊貼
  非 ASCII 即紅——這一類永遠進不來（macOS BSD grep 亦可跑）。
- 註：ubuntu／Windows selftest 與 ShellCheck 於 PR #7 首次雲端驗證全綠；本修復使 macOS job 轉綠。

## [0.12.0] - 2026-07-14

### 新增 (Added) — 迭代 6：檢討迴路（retro loop）
- **`sage retro <任務名> [目標目錄]`**（`scripts/retro.{sh,ps1}` + 兩 dispatcher 接線）：verify 真綠後
  30 秒生成一則 3 問檢討骨架到 sage 倉 `retro/`（UTC 零填充檔名，字典序即時間序；PS 側
  InvariantCulture＋PS location 錨定＋LF 生成物，兩平台位元組等價）。**提醒非強制**：不進任何
  判定路徑，verify 只在全綠訊息尾多一行提示（exit 碼零改動）。
- **每週自我改進迭代**：`checklists/weekly-retro.md`（讀 retro/ 游標後條目 → 彙總排頻次 → 選
  top 1–3 → 改 SOP 的任務自己走 SAGE → RELEASE 流程 → 人 R5 後合入）＋ `retro/WEEKLY.md`
  游標日誌。排程喚醒屬 agent session 環境配置，不在本倉。
- **`templates/acceptance-patterns.md`**：驗收範式庫 4 型（bugfix/CLI/API/資料轉換），bugfix 型
  含「修前會紅的復現命令」鐵則。

### 變更 (Changed) — 六項弱點改善（文件層，對應 2026-07-14 Claude+SAGE 評估）
- `prompts/01-spec.md`：lock 前紅隊 RULE——「這套驗收下最爛但仍能全綠的實作長什麼樣？」；
  起草驗收 agent ≠ 實作 agent（P1）。
- `prompts/04-review-crosscheck.md`：lens 8「清單外品質」（防對清單過度優化——Goodhart 緩解）。
- `checklists/final-acceptance.md`：C 段加「清單外即興抽查」；D 段「綠 ≠ 免 code review」；
  復盤鉤子擴為 lessons＋retro 雙鉤。
- `checklists/goal-gates.md` GATE-3：三條上限/審計 checkbox 補具體操作註（headless 旗標例）。
- `checklists/routing.md`：探索/原型/設計向明文出口——不進 SAGE，收編時走 R6＋補驗收。
- `SAGE_RULES.md` R5 用法注（非语义变更）：親跑可批次结算；機器綠當前置濾網。
- RELEASE 流程加兩條：修閘門 bug 先寫紅案例；minor 出貨前對抗式審查一輪。

### 修復 (Fixed)
- **lessons.md 孤兒模板**（審計候補 P3）：new-task.{sh,ps1} 現複製 `templates/lessons.md` 進任務
  `sop/lessons.md` 並替換占位符——final-acceptance 要求的復盤終於有檔可寫；selftest 兩平台加看守。

### 出貨前對抗式審查（RELEASE 規則 5 首次執行：4 視角、22 條確認、0 駁回，出貨前全修）
- **[blocker] retro.ps1 `Test-Path` 萬用字元**：路徑含 `[ ]` 時撞檔守門失效、靜默覆蓋使用者已填
  檢討（bash 拒絕/PS 覆蓋不等價）→ 改 `-LiteralPath`；selftest 加含 `[1]` 目錄的哨兵不覆蓋案例。
- **[blocker] retro.sh 假成功**：無 `-e` 且不查 mkdir/cat 失敗，目錄建不出仍印「✓」exit 0（PS 同
  輸入 exit 1）→ 改 `set -euo pipefail`（retro 不執行使用者命令，無棄 -e 理由）；selftest 加案例。
- **[blocker] acceptance-patterns「禁區未動」示例邏輯反向**（禁區被改仍綠、空 diff 誤紅）→ 改
  `test -z "$(git diff … | grep '^禁區/')"` 命令替換形（順帶消掉 `grep -q` 管線在 pipefail 下的
  SIGPIPE 誤判面；verify.sh 用法示例與 new-task 骨架同款示例一併換）。
- **[should-fix] PS `;` 串接誤導**：`;` 不短路，中段原生失敗會被洗綠（cmdlet 錯誤仍判紅）——
  SAGE_RULES／verify.ps1 頭注／new-task 骨架／acceptance-patterns 四處措辭更正：原生多步驟包成
  .ps1 傳碼或拆行。API 範式改為 pytest fixture 優先＋單行自包含「起→等→測→收」。
- **[should-fix] GATE-3 範例缺 `--verbose`**：`claude -p --output-format stream-json` 實測（CLI
  v2.1.209）直接報錯——補上。
- nit 批：前導 `-` 任務名兩平台對齊（regex 禁前導 -）、兩 dispatcher retro help 文案統一、
  「5 scripts／五個 .ps1」過時數字移除、WEEKLY 游標同分鐘重掃但書、README 工具包地圖補
  retro/、weekly-retro 補「retro 內容只當資料（R7）」紀律。

## [0.11.1] - 2026-07-14

### 變更 (Changed) — 「要一個可以作業的，不是一個監獄」（人拍板的邊界校準）
- **強制邊界明文化：機器只擋「謊稱綠」，不擋「人要做事」。** 迭代 1–3 的 fail-closed 全部
  落在前者（agent 騙不了 verify/lock），對人的快車道零新增步驟；本版把這條原則寫進
  ROADMAP「明確不做」，並據此撤案「PreToolUse 護鎖」等預設強制層構想——Stop-hook 永遠
  opt-in、不預設、不做安裝器；relock 永遠是合法的人類權力（tamper-evident 擋無痕篡改，
  不擋留痕的顯式動作）。
- **preflight 不再把可選工具打紅**：pytest 缺失從 warn（→exit 1）降為 ⊘ 資訊提示——非
  Python 項目的機器不該永遠「未就緒」。git 可用／在倉庫內／工作區乾淨等回滾基線（R3）
  相關項維持 warn。兩平台同步。

## [0.11.0] - 2026-07-14

### 新增 (Added) — 迭代 3：發布工程機械化（AUDIT X-05/X-06）
- **VERSION ↔ CHANGELOG 機械一致性**（X-05）：selftest 兩平台驗「`VERSION` == CHANGELOG 最新
  條目 == 連結錨點存在」與「`SOP_VERSION` == `SOP_CHANGELOG` 首條（凍結快照防意外漂移）」；
  配合既有「`sage version` == VERSION」看守，版本三角閉合。CI 跑 selftest 即閘住。
- **編碼不變量機械化**（X-06）：selftest 驗 DESIGN 明定規則——`sage`/`*.sh` 必 LF 無 BOM、
  含非 ASCII 的 `*.ps1` 必有 UTF-8 BOM（可攜寫法，macOS BSD grep 亦可跑）。故意提交 CRLF
  的 .sh → CI 紅。
- **RELEASE 流程文件化 + 歷史 tag 對應驗證**：本檔頭部新增三步發布流程（tag 只打合入 master
  的 commit）。歷史「版本→commit」對應已逐一機械驗證（tag 目標 commit 的 `VERSION` 檔內容
  == tag 名，且 master 可達）；v0.9.0 遠端已存在（53f21ea，採用不覆寫）。其餘由倉庫管理者
  執行補打（agent 環境 tag push 被 403 擋下，僅能推指定分支）：
  ```
  git tag -a v0.1.0 52c2b1c -m v0.1.0 && git tag -a v0.4.0 6b2cb1b -m v0.4.0
  git tag -a v0.5.0 5aea492 -m v0.5.0 && git tag -a v0.6.0 ac44233 -m v0.6.0
  git tag -a v0.7.0 f664a11 -m v0.7.0 && git tag -a v0.8.0 f024523 -m v0.8.0
  git tag -a v0.8.1 cbcb7ea -m v0.8.1
  git push origin v0.1.0 v0.4.0 v0.5.0 v0.6.0 v0.7.0 v0.8.0 v0.8.1
  ```
  0.2.0/0.3.0 無對應 commit，不猜測、不補打。

### 說明 (Note)
- ROADMAP 迭代 3 的 3.1（多平台 CI）已由上游 0.9.0 完成，本版不重做；本版把 3.2/3.3 以
  「檢查進 selftest、CI 跑 selftest 即生效」的最薄方式落地，不動 Lab 的 ci.yml。

## [0.10.1] - 2026-07-14

> 本版全部來自對 v0.10.0 diff 的**多 agent 對抗式審查**（4 視角並行 + 每條發現獨立驗證者
> 實測駁斥）：17 條確認（去重後 10 個獨立問題）、4 條駁回。審查自己的修，修自己的審。

### 修復 (Fixed)
- **dispatcher 旗標轉發（W-04 後半，0.10.0 漏修卻標完成）**：`sage verify x -AllowUnlocked`
  經 sage.ps1 被陣列 splat 靜默吞掉（bash exit 0 / PS exit 2 不等價；且 B-08 封死 env 後
  Windows 經 dispatcher 無合法 allow-unlocked 途徑）——verify 分支現顯式偵測並轉發；
  selftest 加兩平台等價案例。
- **「統一錨定 PS location」漏修 new-task.ps1**：相對 BaseDir（`sage new x .`）在 in-process
  dispatcher 下 ReadAllText 按行程 cwd 解析 → 中途炸掉留半成品目錄（違反剛立的 W-09/R3
  原則）——與 acceptance-lock/crosscheck 同款錨定；selftest 加相對 BaseDir 案例。
- **`.lock` 第三欄洩漏本機絕對路徑**：0.10.0 的錨定順手把錨定後路徑寫進要 commit 的鎖檔
  第三欄與訊息（.sh 寫使用者原樣路徑）——現顯示/寫檔用原樣路徑、僅 IO 用錨定路徑；
  selftest 加第三欄原樣斷言。
- **鎖時間戳文化敏感（0.10.0 自己引入的倒退）**：`ToString('yyyy-MM-ddTHH:mm:ssZ')` 跟隨
  當前文化的曆法/分隔符（ar-SA 寫出非西曆年），且格式看守攔不住——補 InvariantCulture；
  selftest 加 ar-SA 文化案例。
- **W-05 後半（audit 修法明列、0.10.0 只做一半）**：function/alias 包裝的非原生 reviewer
  失敗不設退出碼，crosscheck.ps1 仍「✓ 完成」+ 0-byte review——成功判定加輸出非空；
  `.err` 檔同步歸一 UTF-8 無 BOM（PS5.1 的 `2>` 寫 UTF-16LE）。

### 強化 (Hardened) — 兩個被攻擊者視角證明空轉的看守
- **R9 正文看守是空殼閘**：`grep 'R9'` 放個只含「R9」三 bytes 的檔就繞過——改為 R1–R9 逐條
  + `acceptance-lock`/`fail-closed` 機制詞全查（仍為 tamper-evident 定位）。
- **B-10 看守看不住 B-10**：rc∈{0,1} 斷言接受 0，而 0 正是「永遠 exit 0」原病灶——加
  「非 git 目錄（必有 warn）→ 必須 exit 1」映射釘死案例。

### 文件 (Docs)
- `SAGE_RULES.md` 驗收行串接說明補 PowerShell 語法（PS 5.1 無 `&&`，與 verify.ps1 頭注一致）。
- ROADMAP 迭代 2 STATUS 更正歸因：2.6 樁跨平台係上游 0.9.0 完成；2.3 於 0.10.1 才真正補齊。

## [0.10.0] - 2026-07-14

### 新增 (Added)
- **`SAGE_RULES.md`——鐵律 R1–R9 正文回歸單一事實源**：0.9.0 的 Lab 轉向把 AGENTS.md 換成
  Workflow Lab 規則後，R1–R9 正文全倉失蹤（`sage rules` 印的不再是鐵律、sop-run.js 叫 agent
  去 README 讀不存在的規則）。現自 v0.8.1 AGENTS.md 遷回為 `SAGE_RULES.md`（R9 補上 0.9.1 的
  空驗收集條款、R5 補上「自動閘門≠merge 授權」）；`sage rules`／`sage.ps1 rules`、
  `prompts/01-spec.md`、`workflows/sop-run.js`、README SOP 段全部改指它；selftest 兩平台加
  「`sage rules` 必含 R9」看守案例。Lab 工作衝突時仍以 `AGENTS.md` 為準（分工不變）。

### 修復 (Fixed) — 迭代 2 雙平台等價批次（AUDIT 2026-07-13）
- **W-04** `sage.ps1`：`$Rest` 為 `$null` 時 splat 塞入 `$null` 位置參數，`sage lock/check/verify`
  不帶檔名全數壞掉——現改空陣列；selftest 加 `sage check` 預設檔名案例。
- **B-10/W-06 等價** `preflight.{sh,ps1}`：退出碼可機械判定（0=就緒、1=有需注意項）；.ps1 修
  三處 `$LASTEXITCODE` 殘留誤判（git 未安裝仍報「✓ 工作區乾淨」）。
- **W-05** `crosscheck.ps1`：未定義 reviewer 現回 127（等價 bash 版），不再誤報「✓ 完成」。
- **W-07** `crosscheck.ps1`：review 輸出不再用 `1>` 重定向（PS5.1 會寫成 UTF-16LE），改捕获後
  以 UTF-8 無 BOM 寫出，與 bash 版產出一致。
- **W-09** `new-task.ps1`：git 不可用或起始 commit 失敗 → exit 1（R3 回滾基線未建立不得回報
  「✓ 任務已建立」）；selftest 加無 git 案例。
- **W-10** `sage.ps1 rules`：`Get-Content` 補 `-Encoding UTF8`，中文系統 PS5.1 不再亂碼。
- **X-04** `scripts/*.sh` 全部補 executable bit（Linux/macOS fresh clone 後 `./verify.sh` 直接可
  跑）；selftest 加看守。
- **時間戳等價** `acceptance-lock.ps1`：鎖時間戳改 UTC Z 格式，與 .sh 完全一致；selftest 兩平
  台加格式看守。
- **相對路徑潛伏 bug**（本輪新增看守案例挖出）：`acceptance-lock.ps1`／`crosscheck.ps1` 用
  `[System.IO.File]` API 讀寫，相對路徑按「行程 cwd」解析，而 `Set-Location`/`Push-Location`
  不改行程 cwd——經 `sage` dispatcher（in-process）在任務目錄跑 `sage check` 即踩中。現統一
  錨定到 PowerShell location。
- **selftest.ps1 自身 fail-open**（同上挖出）：try 區塊中途終止性錯誤會跳過剩餘案例仍報
  「0 失敗」exit 0——補 catch 記失敗，自檢自己 fail-closed。

## [0.9.1] - 2026-07-14

### 修復 (Fixed) — 驗收信任錨加固（AUDIT 2026-07-13 迭代 1，全部附 selftest 負向案例）
- **verify.sh 假綠面（B-01/B-02/B-07/W-02）**：驗收行改在獨立子 bash 執行
  （`bash -o pipefail -c`）——驗收行裡的 `exit` 不再提早終結 verify 假綠收場（連官方範例
  寫法都會中招）、`fail=0` 之類賦值洗不掉計數器、`cd` 不再把證據日誌劈到別的目錄（LOG
  同步改絕對路徑）、不繼承本腳本的 `-e/-u`（貼近人手跑）；`pipefail` 刻意保留——管線中段
  失敗（如 `pytest | tee log`）必須紅，fail-closed 優先。行間語義明文化：每行獨立子行程，
  cd/變數不跨行（需同行 `&&` 串），verify 用法說明與 new-task 骨架同步標注。
- **verify.ps1 假綠面（W-01/W-02）**：每行改在獨立子 PowerShell 行程執行（`-EncodedCommand`
  wrapper，`$null |` 空 stdin 等價 `</dev/null`）；輸出中**任一**布林 `False` 判不通過——
  `Test-Path` 缺檔、多路徑檢查不再假綠；驗收行裡的 `exit` 只終結子行程；wrapper 內非零退出
  碼折疊為 1——PS 腳本型驗收（`& check.ps1` 內 `exit 256`）不再被 Unix 8-bit 行程邊界截斷洗
  綠（巢狀原生行程的截斷是所有 runner 共有的 OS 事實，不在此列）；子行程啟動失敗視為 127
  不通過，不沿用殘留 `$LASTEXITCODE` 假綠（fail-closed）。
- **verify.{sh,ps1} 空驗收集（B-04）**：0 條驗收命令 → 拒絕認證 exit 2（new-task 生成的純註解
  骨架 lock 後不再可直接認證「全綠」）。
- **verify.sh 讀行（B-03/B-09）**：無尾換行的最後一行不再被靜默跳過；逐行剝尾 CR，CRLF
  驗收檔不再每條 127。
- **verify.sh 鎖檢誤診（B-06）**：區分「驗收集被改（TAMPERED）」與「校驗工具跑不起來」，
  不再一律誤報 TAMPERED；兩者皆維持 fail-closed exit 2，acceptance-lock 原始輸出進日誌。
- **acceptance-lock.sh（B-05/X-02）**：`sha256sum` 缺失時 fallback `shasum -a 256`（macOS 原生
  可用）；雜湊結果格式校驗，工具壞掉不再寫出空 hash 壞鎖（fail-closed）。
- **acceptance-lock.ps1 雜湊等價（W-03）**：改位元組級（濾 0x0D 後 SHA256），與 bash
  `tr -d '\r' | sha256sum` 完全一致——BOM/孤立 CR/非 UTF-8 位元組不再造成 .sh/.ps1 互判
  TAMPERED（既有無 BOM 檔案的 .lock 不受影響，已驗 dogfood 與 examples 兩鎖一致）。

### 移除 (Removed)
- **`SAGE_ALLOW_UNLOCKED` 環境變數後門（B-08/D-04/W-08）**：未文件化、可無痕降級 R9
  fail-closed 且日誌謊稱「顯式」；現只認命令列 `--allow-unlocked` / `-AllowUnlocked`（R5：
  跳過防篡改必須人顯式敲在命令上，留痕如實）。

## [0.9.0] - 2026-07-13

### 新增 (Added)
- macOS/Linux `sage` dispatcher 與不需 sudo 的 user 級安全 installer。
- Agy-first、legacy Gemini fallback 的 Bash/PowerShell crosscheck adapter。
- Ubuntu、macOS、Windows PowerShell、ShellCheck、actionlint 的 GitHub Actions CI。
- `sage version`／`sage.ps1 version`，讓安裝後版本可機械查驗。

### 變更 (Changed)
- R5 明確區分「自動閘門通過」與「人類最終驗收完成」；自動系統 MUST 保持
  `r5_human_verification=pending`，不得把 automated pass 當作 merge 授權。
- Claude Workflow 與 Stop-hook 移除個人電腦絕對路徑，改為腳本相對定位或
  `SAGE_ROOT` 環境變數。
- CI 的 `push` 只監聽 `master`，避免 PR branch 同時由 push／pull_request 重複執行。

### 安全 (Security)
- Draft PR、GitHub CI 或 agent 自報成功均不構成 R5；ready／merge 仍須人類審批。

## [0.8.1] - 2026-06-18

### 新增 (Added)
- `README.md` 增 INSTALL 段：`sage` 命令的本機一次性安裝（用戶 profile dot-source `sage.ps1` + `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`；**user 級，非系統級**），方便換機 / 重裝復原。

## [0.8.0] - 2026-06-18

### 修复 (Fixed)
- **R9 收紧（回应 Codex 审计 C1/C2）**：`verify` 现在 **fail-closed**——该锁却没锁 → 拒认证（exit 2），取消原本的 fail-open；临时跳过需显式 `--allow-unlocked` / `-AllowUnlocked`。`acceptance-lock lock` 在锁已存在时**拒绝静默重锁**，改验收集需显式 `relock`（git 留痕）。把"静默重锁 / 删锁"两条绕过从默认可行变为需显式动作。
- `README.md` 至高条款 `R1–R8` → `R1–R9`（改名后遗留漂移，Codex C4）。
- `selftest.{ps1,sh}`：开头注释"四个"→"五个"；新增 `preflight` 测试（现真测 5 个脚本）；新增 C1（拒重锁 / relock）、C2（无锁 fail-closed）用例。

### 说明 (Note)
- R9 定性为 **tamper-evident**（仍可被故意 `relock` / 改锁的 agent 绕过，非 tamper-proof）；真正强制靠 `HOOKS.md` 的带外 Stop-hook。AGENTS.md R9 / DESIGN P3 措辞已据此校正。

## [0.7.0] - 2026-06-18

### 变更 (Changed)
- **方法论定名 SAGE**（**S**pec → **A**cceptance → **G**ate → **E**vidence；绿是验出来的，不是声称的）：`README.md` / `AGENTS.md` 标题与缩写说明就位。
- 命令行从 `sop` 改名 **`sage`**（`sage.ps1` 取代 `sop.ps1`；用户级 `profile.ps1` 已指向新文件）。子命令不变：new/lock/check/verify/crosscheck/preflight/test/rules。

## [0.6.0] - 2026-06-18

### 新增 (Added)
- `AGENTS.md`：把鐵律 R1–R9 + 剂量 + 六道闸 + 应用步骤做成赢家约定（AGENTS.md）格式，作为 agent 规则的**单一事实源**；`CLAUDE.md` 一行指向它（Claude Code 也吃到）。
- `dogfood/`：首次真实 dogfood——拿 SOP 自己的 selftest 当真实可机械验收，`acceptance-lock` 锁定 → 亲跑 `verify` → 真绿（exit 0），含 lessons（N=1，诚实标注）。

### 修复 (Fixed)
- **R9 跨机器误报**：`acceptance-lock`（PS/bash）哈希前归一化 CRLF→LF，使锁经 git EOL 规范化后跨 checkout 仍稳定（否则换机 `verify` 误报 TAMPERED）。**由首次 dogfood 挖出并当场修复。**
- `verify.{ps1,sh}` 改为委派 `acceptance-lock check`（哈希逻辑去重，DRY）。

### 变更 (Changed)
- `README.md` 规则段不再重复 R1–R9，改为指向 `AGENTS.md`（去重防漂移）。

## [0.5.0] - 2026-06-18

### 新增 (Added)
- **R9 防篡改闸**：`scripts/acceptance-lock.{ps1,sh}`（lock/check 验收集 sha256）+ `verify.{ps1,sh}` 在验收集被改动时**拒绝认证绿**（exit 2，不执行任何验收命令）。把支柱 P3「不信自报绿」从自律升级为**机制**——agent 偷偷改松 acceptance 即被机械拦截。
- `HOOKS.md`：可选的 Claude Code Stop-hook（agent 停止时自动跑 acceptance-lock check），opt-in，默认不装。
- `selftest.{ps1,sh}` 扩充防篡改用例（lock→check 过→改后 check 拒→verify 拒认证 exit 2）；两平台实测 **16/0 通过 exit 0**。

### 变更 (Changed)
- `README.md` 新增鐵律 R9 与 scripts 清单；`DESIGN.md` P3 标注「已机制化」；`final-acceptance.md` C 段加「验收集锁定」把关项。
- selftest 计数由「四个」改「五个」脚本。

## [0.4.0] - 2026-06-18

### 新增 (Added)
- `workflows/sop-run.js` — **opt-in 形态2 编排器**（Claude Code Workflow 脚本）。跑 SOP 安全前半段：Plan → 背靠背多审 → 汇总分歧 → 起草 /goal + 六道闸，跑完停在人工闸。它不写代码、不动 git、不跑 verify、不做不可逆操作，不宣布「绿」。author ≠ grader（起草与审查为不同 agent）。
- `workflows/README.md` — 形态2 层说明与调用方式。

### 不变 (Unchanged)
- 内核 KEEP-THIN 仍是默认形态；形态2 为 opt-in 层，仅在主动调用时介入。
- 鐵律 R1/R3/R5/R8 不变；验收裁决权仍在人（人亲跑 verify）。

### 备注 (Note)
- 本版有意识地放宽 DESIGN.md 非目标#1（不做自动编排程序）——作为 opt-in 层，不改默认。

## [0.3.0] - 2026-06-18

### 變更 (Changed)
- **全倉改為 AGENT-FACING 格式**：全部 SOP markdown（README/DESIGN/prompts/checklists/templates/example）重排成 agent 指令格式——祈使句 + MUST/MUST NOT、編號 ID（R# 鐵律 / P# 支柱 / GATE-# 閘 / STEP-# 流程 / ROUTE 分流）、機器可判條件、決策表、why 壓一行、刪動機性敘述。人類可讀性讓位於 agent 消費效率。
- 跨文件交叉引用統一（如 final-acceptance→R5、goal-gates→R1–R7、CONTRACT→GATE-5、各 prompt→R7/R8）。
- prompts 改為 GOAL/MUST/INPUT/OUTPUT 契約格式；templates 改為 (required) 欄位 schema。

### 不變 (Unchanged)
- 內核語義不變（P1–P6 支柱、R1–R8 鐵律、A/B/C 分流、六道閘、13步），只改表達格式。
- 文件名與目錄結構不變（scripts/new-task.* 仍依賴原路徑）。
- scripts/*.sh、*.ps1 邏輯不動。

## [0.2.0] - 2026-06-18

### 新增 (Added)
- **第六條設計支柱 + 鐵律 8：完成/進度呈現給人時優先「可看的成品」**（截圖 / 跑起來的 UI / 真實輸出 ＋「當前在做哪一步」），不是大段文字＋縮寫。理由：支柱 3「不信自報綠」要成立，綠必須讓人看得見，否則人的最後一道把關會退化成橡皮圖章。
- `DESIGN.md`：新增支柱 6（標題「五條→六條」）
- `README.md`：新增鐵律 8
- `checklists/final-acceptance.md`：C 段新增「成品以可看形式呈現」把關項
- `prompts/01-spec.md`、`prompts/05-goal.md`：要求進度/完成用截圖·可點預覽·真實輸出呈現，文字壓到最少

## [0.1.0] - 2026-06-16

首個可落地發布版（含跨平台 PowerShell 版與自检）。

### 新增 (Added)
- PowerShell 版腳本 `new-task.ps1` / `preflight.ps1` / `verify.ps1` / `crosscheck.ps1`（UTF-8 BOM，Windows 原生可跑）
- 自检腳本 `selftest.sh` / `selftest.ps1`：在臨時目錄驗證四個腳本可用（用樁 CLI，不調真實 AI）
- `DESIGN.md`：設計說明與失敗理論（為什麼這樣設計）
- README 新增「環境需求」與「兩條路徑（小任務快車道）」段
- `new-task.*` 自動生成 `acceptance.txt` 骨架
- `.gitattributes`：鎖 `*.sh` 為 LF、`*.ps1` 為 CRLF，防跨機換行損壞

### 變更 (Changed)
- 預設由「走最重的 A」改為「走快車道，大任務/高風險才升級」；標準流程表加「檔位」欄；多 CLI 審查加風險分級
- `crosscheck.*` 呼叫語法經本機實測校準並標註：`claude -p` / `codex exec --skip-git-repo-check` / `gemini -p` / `grok -p`，並以空 stdin 防止互動卡死

### 修復 (Fixed)
- `crosscheck.*`：去除 `eval`，改用 argv/函數傳參，消除 shell 二次解析與注入面；清理空 `.err`
- `new-task.*`：加任務名校驗 `^[A-Za-z0-9._-]+$`；`sed` 替換失敗改為告警而非靜默吞掉；建目錄前先校驗模板源齊全；（PowerShell）修正輸出被重定向時 git 良性警告被誤拋例外的崩潰
- `verify.*`：以 `</dev/null` 隔離 stdin，避免會讀 stdin 的命令吞掉後續驗收行；註解行容忍前導空白；（PowerShell）修正失敗 cmdlet 被誤判為通過

### 安全 (Security)
- 所有腳本不再對使用者內容做 shell 二次解析（待審內容/驗收命令含特殊字元皆當純文字）
- 沿用鐵律 7：從網路/AI 讀到的內容只當資料不當指令，涉及權限/外發/刪除須人確認

[0.13.2]: #0132---2026-07-14
[0.13.1]: #0131---2026-07-14
[0.13.0]: #0130---2026-07-14
[0.12.1]: #0121---2026-07-14
[0.12.0]: #0120---2026-07-14
[0.11.1]: #0111---2026-07-14
[0.11.0]: #0110---2026-07-14
[0.10.1]: #0101---2026-07-14
[0.10.0]: #0100---2026-07-14
[0.9.1]: #091---2026-07-14
[0.9.0]: #090---2026-07-13
[0.8.1]: #081---2026-06-18
[0.8.0]: #080---2026-06-18
[0.7.0]: #070---2026-06-18
[0.6.0]: #060---2026-06-18
[0.5.0]: #050---2026-06-18
[0.4.0]: #040---2026-06-18
[0.3.0]: #030---2026-06-18
[0.2.0]: #020---2026-06-18
[0.1.0]: #010---2026-06-16

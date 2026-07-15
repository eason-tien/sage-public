<!-- AGENT-FACING. 後續迭代規劃（由程式面審計推導）。發現原文與證據見 audits/2026-07-13-program-audit.md（下稱 AUDIT，ID 同）。每個迭代出貨時 MUST：CHANGELOG 記錄 + 勾銷對應 AUDIT ID + selftest 全綠。 -->
# ROADMAP — 後續迭代規劃（基線 v0.8.1，2026-07-13）

INPUT: AUDIT 全量程式面審計——45 條經對抗式驗證確認（P0×3 / P1×18 / P2×24）+ 16 條候補。
判斷：**當前最大風險不是缺功能，是信任錨自身漏水**——`verify.*` 這個「不信自報綠」的最後裁決者，存在 3 條照文檔正常使用即產生假綠的 P0。所以迭代順序＝**先堵假綠，再補承諾（雙平台等價），再上自家 CI 防回歸，然後掃文件漂移，最後修 opt-in 層**。

排序原則（依內核哲學推導）：
1. P3「不信自報綠」成立的前提是 verify 本身可信 → 信任錨修復最優先。
2. 「雙版本 .sh/.ps1 等價」是 DESIGN 明文承諾 → 等價缺口第二。
3. 一個主打 R1 機械驗收的專案自己沒有 CI，是哲學自相矛盾 → 第三。
4. 文件漂移（R9 掃除）成本低但影響 agent 接地 → 第四，可與 1–3 並行插隊。
5. 形態2/hook 是 opt-in 層，壞了不傷內核 → 最後。

## 迭代 1（已出貨：v0.9.1，2026-07-14）— 驗收信任錨加固【最高優先】
> STATUS: **完成**。1.1–1.9 全數落地；對抗式審查另抓出並修掉本輪 diff 自己引入的迴歸
> （pipefail 丟失、PS 子行程啟動失敗吃殘留退出碼等，見 CHANGELOG 0.9.1）。
> 實測：selftest.sh 47/0、selftest.ps1 29/0（pwsh 7.4.17）、shellcheck 0 錯、
> BOM+CRLF 鎖跨 .sh/.ps1 互換 OK。原基線的四條假綠復現全部轉紅。

GOAL: 讓「照文檔正常使用 verify/lock」不存在任何假綠路徑。全部是 1–5 行的點修，零新抽象（KEEP-THIN 不動）。

| 項 | AUDIT | 內容 |
|---|---|---|
| 1.1 | B-01 B-02 B-07 W-02 | verify.sh 驗收行改子 shell 隔離執行（`( eval "$cmd" )`），一次解決：`exit` 提早假綠、`fail=0` 洗綠計數器、`cd` 劈日誌、set -u/pipefail 洩漏；LOG 轉絕對路徑 |
| 1.2 | W-01 W-02 | verify.ps1：管線輸出為 `$false` 判不通過（Test-Path 假綠）；驗收行改子行程執行（`pwsh -NoProfile -Command`）杜絕裸 exit 終結宿主 |
| 1.3 | B-03 B-09 | read 迴圈補 `|| [[ -n "$cmd" ]]`（無尾換行最後一行被吞）；每行剝尾 CR（CRLF 檔與 lock 歸一化語義對齊） |
| 1.4 | B-04 | 空驗收集（n=0）→ exit 2 不認證，.sh/.ps1 同步（new-task 純註解骨架 lock 後可直接認證綠是最常見人為失誤） |
| 1.5 | B-05 X-02 | acceptance-lock.sh：空 hash 防護 + `shasum -a 256` fallback（macOS 原生無 sha256sum，鎖鏈整條壞） |
| 1.6 | W-03 | lock 雜湊 .ps1 改位元組級（濾 0x0D 後 SHA256），與 bash 完全等價；既有 .lock 走顯式 relock 遷移 |
| 1.7 | B-08 D-04 W-08 | 處置 SAGE_ALLOW_UNLOCKED 後門：建議刪除 env 通道只認命令列旗標；若保留必須文件化 + 日誌如實標注來源 + .ps1 補等價 |
| 1.8 | B-06 | verify.sh 區分「鎖被改」與「校驗工具不可用」兩種 exit 2，錯誤訊息不再誤導 |
| 1.9 | （B/W 全部） | **selftest 每修一項配一條負向案例**（現有 selftest 對整個 fail-open 面零覆蓋——本次全部 P0/P1 都在 selftest 綠燈下存在） |

機械驗收（人親跑，R5）：
```
bash scripts/selftest.sh                                      # 全綠 exit 0（含新增負向案例）
printf 'exit 0\nfalse\n' > /tmp/a.txt && bash scripts/verify.sh --allow-unlocked /tmp/a.txt; test $? -eq 1
printf 'true\nfalse'    > /tmp/b.txt && bash scripts/verify.sh --allow-unlocked /tmp/b.txt; test $? -eq 1
printf '# only comment\n' > /tmp/c.txt && bash scripts/verify.sh --allow-unlocked /tmp/c.txt; test $? -eq 2
```

## 迭代 2（已出貨：v0.10.0 + v0.10.1，2026-07-14）— 雙平台等價 + `sage` 入口補齊
> STATUS: **完成**。2.1（sage bash 入口）與 2.6 的 selftest 樁跨平台已由上游 0.9.0 先行落地；
> 2.2/2.4/2.5 與 2.6 的時間戳統一於 0.10.0 落地；2.3 的旗標轉發與 W-05 後半（空輸出判失敗）
> 於 0.10.1 補齊（0.10.0 曾漏，經多 agent 對抗式審查抓回，見 CHANGELOG 0.10.1）。
> 另追加「R1–R9 正文回歸單一事實源」（`SAGE_RULES.md`，修復 0.9.0 Lab 轉向造成的規則斷鏈，
> 含 4.1 的 D-01 與 sop-run.js 接地改指新檔）。selftest 兩平台各加看守案例。

GOAL: 兌現「雙版本 .sh/.ps1 等價」與「支援 Git Bash/WSL/macOS/Linux」兩條既有承諾。

| 項 | AUDIT | 內容 |
|---|---|---|
| 2.1 | X-03 | 新增 `sage.sh`（bash 函數版 dispatcher，子命令與 sage.ps1 一一對應）；README INSTALL 補 bash/zsh 段（source 一行） |
| 2.2 | X-04 | `git update-index --chmod=+x scripts/*.sh sage.sh`（clone 後 `./verify.sh` 不再 Permission denied） |
| 2.3 | W-04 | sage.ps1：`$Rest` 為 $null 時 splat 壞掉所有預設檔名子命令——一行修復 + 旗標轉發 |
| 2.4 | W-05 W-06 W-09 B-10 | 退出碼等價批次：crosscheck.ps1 未定義 reviewer 誤報 ✓、preflight.ps1 殘留 $LASTEXITCODE、new-task.ps1 無 git 仍 ✓、preflight.sh 永遠 exit 0 |
| 2.5 | W-07 W-10 | 編碼批次：crosscheck.ps1 重定向在 PS5.1 產 UTF-16 檔、`sage rules` 讀 AGENTS.md 亂碼 |
| 2.6 | 候補 | 順帶：lock 時間戳格式統一（UTC Z）、selftest.ps1 樁命令改跨平台寫法（pwsh on Linux 可跑，為迭代 3 的 CI 鋪路） |

機械驗收：兩平台 `selftest` 全綠 exit 0；Linux fresh clone 後 `./scripts/verify.sh` 可直接執行；`sage.sh` 與 `sage.ps1` 對同一組輸入退出碼一致（selftest 加等價斷言）。

## 迭代 3（已出貨：v0.11.0，2026-07-14）— 自家 CI 機械閘 + 發布工程
> STATUS: **完成**。3.1（多平台 CI）已由上游 0.9.0 先行落地；3.2/3.3 於 0.11.0 以最薄方式
> 落地——檢查全部進 selftest（CI 跑 selftest 即生效，不動 Lab 的 ci.yml）：VERSION↔CHANGELOG
> ↔連結錨點一致性、SOP_VERSION↔SOP_CHANGELOG 凍結快照、編碼不變量（.sh LF 無 BOM／含中文
> .ps1 必 BOM，macOS BSD grep 可攜）。RELEASE 三步流程寫進 CHANGELOG 頭部，明定 tag 只打
> 合入 master 的 commit。歷史 tag：「版本→commit」對應已逐一機械驗證（v0.1.0、v0.4.0–v0.8.1；
> 0.2.0/0.3.0 無對應 commit 不補；v0.9.0 遠端已存在採用之）；推送指令記錄於 CHANGELOG
> 0.11.0，由倉庫管理者執行（agent 環境僅能推指定分支，tag push 403）。

GOAL: 把「換機先跑 selftest」的自律變成機器閘。CI 不是 runtime 抽象層，不違 KEEP-THIN——它正是 R1 哲學用在自己身上。

| 項 | AUDIT | 內容 |
|---|---|---|
| 3.1 | X-01 | `.github/workflows/ci.yml`：ubuntu job（selftest.sh + shellcheck）+ windows job（selftest.ps1 + PSScriptAnalyzer）+ pwsh-on-ubuntu job（等價驗證） |
| 3.2 | X-06 | 編碼不變量機械化：CI 檢查 .sh 為 LF 無 BOM、.ps1 含中文者必有 BOM、scripts/*.sh 有執行位（DESIGN 的規則第一次有機器執行） |
| 3.3 | X-05 | VERSION ↔ CHANGELOG 首版本一致性檢查（10 行腳本進 selftest 或 CI）；發布補打 git tag，流程寫進 CHANGELOG 頭部說明 |

機械驗收：PR 上兩平台 CI 全綠；故意提交一個 CRLF 的 .sh → CI 紅。

## 迭代 4（v0.11.x，純文件，可隨時插隊出貨）— R9 漂移掃除 + 文件收斂
GOAL: agent 接地讀到的規則不再缺 R9、地圖照走不再撞牆。

| 項 | AUDIT | 內容 |
|---|---|---|
| 4.1 | D-01 D-02 O-05 + DESIGN.md:53 | 「R1–R8」→「R1–R9」全倉掃除：prompts/01-spec.md 首行、sop-run.js RULES 接地（改指 AGENTS.md）、DESIGN 形態2 註記 |
| 4.2 | D-03 D-06 | README 13 步地圖補 acceptance-lock 步驟（與 AGENTS.md 应用步骤對齊）；artifacts-example 補 lock 步驟（照範例走不再 exit 2） |
| 4.3 | D-05 | 「快車道」三處定義統一（README 含 STEP 8 vs AGENTS/DESIGN/new-task 三步收工——擇一為準，建議以 AGENTS.md 為單一事實源） |
| 4.4 | D-07 D-09 | dogfood 記錄勘誤（鎖檔引文與 committed .lock 不符、16→20 條）；DESIGN SELFTEST「四腳本」→「五腳本」 |
| 4.5 | 候補 | 順帶核實後處理：HANDOFF 五區塊兩套枚舉、new-task 收尾提示指向舊章節、DESIGN 編碼規則收錄 ASCII 例外、lessons 模板未複製 |

機械驗收：`grep -rn 'R1[-–]R8' --include='*.md' --include='*.js' .` 零命中（除 CHANGELOG 歷史）；照 README 地圖 + artifacts-example 全流程走一遍 exit 0。

## 迭代 5（已出貨：v0.13.0，2026-07-14）— 形態2 編排器與 hook 層修繕（opt-in 層）
GOAL: opt-in 層達到「換一台機器、換一個人也能照文件跑起來」。
> STATUS: **完成**（v0.13.0）。與計畫的兩處偏差（誠實記錄）：
> - 5.1 上游其間曾改為 `import.meta.url` 自推根路徑——實測 Workflow runtime 把腳本包進
>   **非 module** 函式，`import.meta` 是啟動前 SyntaxError，整個腳本根本起不來（比硬編碼
>   更糟的 P0）。回到本表原案精神（根路徑必填參數；表中原寫 `args.repo`，實作沿用既有
>   參數名 `args.sageRoot`），缺 → 零 agent 返回 `hardStop:'NO_SAGE_ROOT'`。
> - 5.5 計畫寫 `node --check`（ESM 包裝），但 ESM 語義與真 runtime 恰好相反（ESM 允許
>   import.meta、禁 top-level return）——改為「同形 AsyncFunction 包裝＋strict、只解析
>   不執行」煙測＋import.meta 負向自證案例，落在 selftest.{sh,ps1} 兩側；CI 三平台覆蓋。
> - 其餘照表交付：5.2 零-agent 早退＋plan/aggregate-null/全 reviewer 亡防護、5.3 clamp
>   整數 1..4、5.4 HOOKS stderr 回灌（SAGE_ROOT 可攜寫法已由上游先行落地，本版只補
>   stderr 管道＋PS `*>&1` 資訊流）、5.6 blockingCount 程式計數；O-06 以 HONESTY NOTE
>   明文標注（不加機制）。
> 機械驗收（已跑）：真 Workflow runtime 兩次冒煙——缺根→`NO_SAGE_ROOT`、缺 spec→`NO_SPEC`，
> usage 實測 **agent_count=0**；`bash scripts/selftest.sh` 全綠（含新煙測與其紅案例）。

| 項 | AUDIT | 內容 |
|---|---|---|
| 5.1 | O-01 D-08 | sop-run.js 硬編碼個人 REPO 路徑 → 改由 `args.repo` 必填傳入（缺 → 立即 return 報錯） |
| 5.2 | O-02 O-03 | 無 spec 時在 Plan 前早退（現在宣稱 hard-stop 但 schema 強制 agent 捏造輸出照跑四 phase）；agent() 回 null 的防護（plan null 即中止、reviews 過濾 null） |
| 5.3 | O-07 | reviewers 參數 clamp（1–4）+ 對齊自家 R4（token/turns 上限意識，至少文件標注） |
| 5.4 | O-04 X-07 | HOOKS.md 文件正確性（讓**選擇裝的人**裝得起來，不推銷安裝）：exit 2 回灌訊息改走 stderr（現在全走 stdout，agent 被擋卻看不到原因）；範例路徑可攜寫法 |
| 5.5 | O-08 O-06 | sop-run.js 進 CI smoke（node --check as ESM）；「不做不可逆操作」的邊界**明文標注即可**，不加機制 |
| 5.6 | 候補 | blockingCount 改程式計數 |

機械驗收（原計畫，實際執行見上方 STATUS）：無 spec 冒煙 → 一個 agent 都不 spawn 即停；語法煙測過。

## 迭代 6（已出貨：v0.12.0，2026-07-14）— 檢討迴路（retro loop）＋六項弱點改善
> STATUS: **完成**。源自「Claude 配 SAGE vs 素身 Claude」評估的六項弱點改善（全文件層）＋
> 新需求「每次執行後檢討、每週自我改進迭代」。人拍板三決策：R5 只做批次稽核用法（不動鐵律）；
> 週迭代=流程文件＋session 排程喚醒；檢討集中存本倉 retro/。
>
> 交付：`sage retro`（兩平台，提醒非強制）、retro/＋WEEKLY.md 游標、checklists/weekly-retro.md、
> templates/acceptance-patterns.md、驗收紅隊 RULE、lens 8 清單外品質、清單外即興抽查、
> 綠≠免 review、GATE-3 操作註、探索/原型不進 SAGE 出口、R5 批次结算用法注、RELEASE 加
> 紅燈先行＋minor 前對抗式審查兩條、lessons 孤兒模板修復（審計候補 P3）。
> 週迭代 Routine 建於 agent session 環境（每週喚醒照 weekly-retro.md 走），不屬本倉交付物。
>
> 機械驗收：`bash scripts/selftest.sh`＋`pwsh -NoProfile -File scripts/selftest.ps1` 全綠（含
> retro/lessons/提示行新看守）；`sage retro demo /tmp/rt` 生成 `YYYYMMDD-HHMM-demo.md`；
> `grep -q '最爛但仍能全綠' prompts/01-spec.md`；其餘逐條見 CHANGELOG 0.12.0。

## 明確不做（防 scope creep；2026-07-14 依人拍板增補「工具不是監獄」邊界）
- **強制的邊界停在「擋假綠」，不擋人**：verify/lock 的 fail-closed 只約束「agent 謊稱綠」；
  不對人的操作加新步驟、新門檻、新檔位。可選工具缺失（如 pytest）只提示不打紅。
- **不再新增預設強制層**：Stop-hook / PreToolUse 護鎖永遠 opt-in、不預設、不做安裝器、
  不寫進任何「必裝」清單（原 5.6 的 PreToolUse 護鎖自此撤案，除非人主動要求）。
- 不做 tamper-proof（R9 維持 tamper-evident 定位——擋「無痕篡改」，不擋「留痕的顯式動作」；
  relock 永遠是合法的人類權力）。
- 不做重編排框架、不加配置層（NON-GOALS 不動；迭代 5 只修既有 opt-in 層的正確性）。
- 不擴 crosscheck 多 CLI 能力（DESIGN 明言「那是最該瘦身處」）。
- AUDIT 駁回的 3 條不重提（理由已記錄在 AUDIT 駁回節）。

# Multi-CLI Workflow Lab

這個倉庫用可重複的基準任務，比較 Codex CLI、Antigravity CLI（Agy）與
Claude Code 的軟件開發流程。目標不是比較聊天表現，而是找出在相同需求下，
哪種角色分工能產生最可靠、最容易審計的改動。

## 原則

- 同一個 fixture、同一份公開需求、同一套隱藏驗收。
- 實作者不得讀取 `benchmarks/hidden/`，也不得修改測試或任務契約。
- 完成由命令退出碼、隱藏測試、diff 完整性與安全掃描共同裁定。
- 不使用任何 CLI 的 dangerous/yolo/bypass-permissions 模式。
- 每個流程都在獨立 Git 倉庫副本中執行。

## 快速開始

```bash
just doctor
just prepare single-codex
just verify single-codex
just list-flows
just run-flow solo-codex solo-codex-1
```

每個流程的 prompt、原始輸出、耗時、階段後 diff 與最終驗證會保存在
`runs/<name>/`。該目錄預設不提交到 Git。

驗證完成後，可明確呼叫 Promotion Gate，把鎖定的 patch 套到新的 `codex/*`
分支、重跑驗收、建立 draft PR，並等待 GitHub CI：

```bash
just promote runs/pilots/issue-123 /path/to/repository codex/issue-123
```

Promotion Gate 不會把 PR 轉成 ready，也沒有 merge 或 auto-merge 操作。

v0.13.2 另提供人類最後使用的 fail-closed merge wrapper；它不是 Promotion 的自動延伸，
而是只接受綁定精確 commit SHA 的人工 R5 簽章。詳見
[`docs/fail-closed-merge.md`](docs/fail-closed-merge.md)。

## SAGE 能力

- 一份 `workflow/task.example.json` 同時定義 route、acceptance、scope、turn/token/USD/time
  預算、Evidence signer 與 draft-only Promotion。
- `python3 workflow/sage.py run|promote|resume-promotion --config <file>` 是統一入口。
- 每個可 Promotion 的 run 必須有 SSH detached signature；Promotion 會發布
  `SAGE Evidence` commit status，但永遠留下 `r5_human_verification=pending` 與
  `merge_authorized=false`。
- runner 以 clone 時的 immutable baseline 計算 candidate；任一 agent stage 非零、移動 HEAD、
  缺少 stage evidence 或產生空 patch 都會 fail-closed，不能升版或簽章。最終 gates 另在全新
  clone 重建 exact binary patch，移除 source remote；在 CodeGraph 與任何 gate 前拒絕靜態
  absolute／越界 symlink，並從 gate environment 移除 provider／CI credentials。這不等於
  hostile-code OS sandbox：候選程式仍與主機共用 filesystem/network；高信任無人值守必須把
  runner 再放進 container／VM。此邊界會寫入簽署的 `result.json.runtime_boundary`。
- `.sage/gates.json` 可用 argv array 加語言 gate，不經 shell 二次解析。
- 12 個真實 repo／12 種主要語言的可攜性結果見
  `reports/real-repo-benchmark.md`。

## 無人值守知識閉環

SAGE 現在以 `knowledge/` 作為 Obsidian vault。每個任務在任何 Agent 啟動前先驗證
Agy、Codex、Claude、Git、Gitleaks、CodeGraph、Obsidian 與 Evidence key，偵測語言並
更新相關知識筆記。三個 CLI 只讀同一份 `SAGE_KNOWLEDGE.md`，避免各自形成不一致記憶。

```bash
python3 workflow/sage.py preflight --config workflow/task.example.json
python3 workflow/sage.py run --config workflow/task.example.json
python3 tools/check_codegraph.py .
python3 tools/check_version_record.py
```

成功任務會自動 patch-bump 並更新 `Projects/<project>/Ver.md`、`Memory.md`、Task note；
失敗任務也會記錄與蒸餾，但不升版。Knowledge snapshots 會放入 run 並由 SSH Evidence
簽章覆蓋。CodeGraph 在派工前及每次 gates 強制 init/sync。
Pre-commit 會拒絕只暫存程式而未暫存 Memory／State／Ver／Task note；CI 另以 PR
base/head 或 push before/head 檢查完整提交範圍。ledger history 必須保持前綴、版本連續，
所有新增 successful records 的宣告聯集必須覆蓋範圍內每個專案變更；最新成功記錄還會以
canonical tree SHA-256 綁定完整版本化 path、mode 與 Git clean-filter 後的 bytes，並重驗全部
Memory／Ver／Task Note。worktree 雜湊使用臨時 index/object DB，因此 CRLF checkout 與 staged／
committed blob 不會落入不同的 byte domain。
因此 merge commit、reports-only tip、同名二次篡改、type change、rename source 或跳過本機 hook
都不能隱藏未升版程式。

Web UI、網站介面、桌面視覺 UI 或 WPF/XAML 設計另有 Stitch 硬門檻。Preflight 會
自動辨識這類任務，要求由 Google Stitch 匯出的 `DESIGN.md`，並在隔離 workspace
鎖定為 `STITCH_DESIGN.md`。Stitch 網頁可使用 Google Ultra 會員帳號登入；無人值守
MCP/SDK 可使用 Stitch API Key 或 OAuth。尚未產生設計且認證不可用時，會在
Agent 派工前停止。WPF 實作以核准的 Stitch 桌面設計系統與畫面為 XAML 依據，不直接
把 HTML 當成 WPF。

## 星光小精靈審計遊戲

`examples/sprite-audit-game/` 是原創 Canvas 小遊戲與輕量 Evidence UI。它包含純函式
遊戲核心、鍵盤／觸控操作、公開及隱藏測試、acceptance lock、HTTP smoke、Biome
與 Gitleaks。啟動：

```bash
cd examples/sprite-audit-game
python3 -m http.server 8080
```

完整自動審計：`python3 tools/audit_sprite_game.py`。綠燈仍不等於人類 R5。

## 安裝 `sage` 命令

Windows PowerShell 可在 `$PROFILE.CurrentUserAllHosts` dot-source 本倉庫的
`sage.ps1`；若本機策略阻擋本地腳本，可由使用者決定是否執行
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。新視窗可直接使用 `sage`。

macOS／Linux 使用 user-level 安裝，不需 `sudo`，也不修改 shell profile：

```bash
bash scripts/install.sh --prefix ~/.local
```

確認 `~/.local/bin` 已在 `PATH`。移除時執行：

```bash
bash scripts/install.sh --prefix ~/.local --uninstall
```

兩個平台皆可執行 `sage version`；輸出必須與根目錄 `VERSION` 一致。任何自動
閘門或 CI 綠燈只代表可交人做 R5 驗收，不代表 ready 或 merge。

人工 R5 後只使用 `tools/merge_pr.py`：它會重新核對五個 GitHub CI jobs、所有回報 checks、
精確 PR head、簽署 Evidence、人工驗收 log 與獨立 `sage-r5` 簽章；真正 merge 還需人在互動
終端輸入完整 PR + SHA。這是 fail-closed 的本機操作層，但不是 GitHub 權限邊界：目前 private
repo 的 protection/rulesets API 因方案限制回傳 403，升級方案或改為 public 並啟用 required
checks 前，有 merge 權限者仍可繞過 wrapper，因此 R5、release 與「server-side 已強制」皆維持 pending。
不升級時不會把含 hidden oracle 與舊歷史的原倉庫直接公開；改由
`tools/public_export.py` 產生兩個 commit、無來源歷史的 `eason-tien/sage-public` 候選，並以
私有 exact-head attestation 與 SSH certificate 綁定公開 tree。完整信任邊界與 required checks
見 [`docs/public-release-topology.md`](docs/public-release-topology.md)。

## Agent-facing SOP 工具包

遠端 `master` 原有的 SAGE SOP 歷史已併入本倉庫，作為較輕量、可跨平台手動使用的
規範工具包；新的無人值守編排器仍以 `workflow/`（單數）為主要入口。兩者分工如下：

- `DESIGN.md`、`HOOKS.md`：SAGE 方法論與可選的帶外防竄改 Hook。
- `prompts/`、`checklists/`、`templates/`：Spec → Acceptance → Gate → Evidence 的人工流程資產。
- `scripts/`、`sage`、`sage.ps1`：Bash／PowerShell 的任務建立、驗收鎖定、驗證、安裝與自測工具。
- `retro/`、`checklists/weekly-retro.md`：執行後 30 秒檢討（`sage retro`，提醒非強制）與每週自我改進迭代。
- `workflows/`（複數）：opt-in 規劃／對抗式審查層；先由 `sop-preflight.py` 建立綁定來源
  HEAD、時效與內容雜湊的 preflight bundle，再以 2–4 reviewers 與機械 quorum/語義守門執行。
  runtime 可偵測 bundle 內容被改動，但 bundle 的來源真實性仍以 trusted launcher 為邊界，並停在人工 gate。
- `VERSION`、`CHANGELOG.md`：目前 v0.13.2 候選與完整產品變更紀錄；正式 release 仍等待
  綁定最終 SHA 的人工 R5。
- `SOP_VERSION`、`SOP_CHANGELOG.md`：保留匯入前 SOP 工具包的 0.8.1 歷史快照。
- `knowledge/Projects/multi-cli-workflow-lab/Ver.md`：整個無人值守專案的獨立 patch 版本；
  三種版本用途不同，不能互相覆蓋。

舊工具包的 R1–R9 鐵律正文以 **`SAGE_RULES.md`** 為單一事實源（`sage rules` 印的
就是它）；Lab 工作發生衝突時仍以 `AGENTS.md`、不可變的 `SAGE_KNOWLEDGE.md` 與機械閘門
為準。

合併後的逆向治理結果、PR #7–#10 失敗 CI 與 0.1.18–0.1.21 本機證據映射，見
[`reports/governance-recovery-v0.13.2.md`](reports/governance-recovery-v0.13.2.md)。

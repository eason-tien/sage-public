# HANDOFF — PR2 R5, merge, and CLI v0.9.0 release

## 1. STATUS

- 完成度：自動候選已完成；PR2 文件修正與新 Evidence 必須先全綠，人工 R5 仍 pending。
- 最後 commit：以 [PR2](https://github.com/eason-tien/sage/pull/2) 顯示的 head 為準；簽署
  manifest 記錄不可變 commit 與 patch hash，本文件不保存自我引用的 SHA。
- 驗收結果：上一個 PR2 head 的五個 CI check runs 與 `SAGE Evidence` 成功；本文件所在
  的新 head 仍必須重跑相同門檻，且自動成功不代表 R5。

## 2. WHAT

- PR2 合併 workflow lab、SAGE SOP 歷史、無人值守知識循環、簽署 Promotion、Stitch UI
  gate、跨平台 CLI／installer 與 GitHub Actions CI。
- PR2 是唯一有效整合候選；較早的 pilot PR 已關閉並由 PR2 取代。
- CLI 產品版本是 `0.9.0`。本次交付文件修正完成後，專案 knowledge ledger 是
  `0.1.16`。兩者是不同 namespace；GitHub Release 標籤與產品名稱使用 `v0.9.0`，
  Release 說明另行註明 ledger `0.1.16`，不得把 ledger 當 CLI 版本。

## 3. WHY

- PR2 取代 pilot PR，避免兩條 PR 同時代表同一產品候選並造成版本、CI 與 changelog
  語意分裂。
- 自動 Evidence、GitHub CI 與人類 R5 分開，避免 Agent 自報綠直接取得 merge 權限。
- 交付文件不硬編 current-head SHA；精確 commit、patch、acceptance hashes 由簽署
  manifest 保存，文件只描述可長期成立的流程與版本關係。

## 4. TRAPS

- `automated_gates_passed=true`、綠色 `SAGE Evidence` 或 GitHub checks 都不是人工 R5。
- Release 只能從已合併的 `master` 建立，不能從 PR branch 或 R5 前的候選建立。
- 目前 private personal repository 的方案沒有 branch protection／rulesets 強制層；
  在方案調整前，PR/R5 是作業政策而非 GitHub 伺服器不可繞過的保證。
- GitHub 原生 private CodeQL、secret scanning／push protection 尚未完整啟用；目前依賴
  CI Gitleaks 與本機門檻。Actions 仍以 major tags 引用，尚未全部 pin 到完整 SHA，
  Docker actionlint image 也尚未 pin digest。
- 簽署 Evidence 存於本機 ignored run；GitHub 只有 commit status，不是可下載的遠端
  attestation artifact。Git commit 本身也未簽署。
- 不得把 `benchmarks/hidden/` 內容交給被測 CLI，也不得讓被測 CLI 修改 tests／policy。

## 5. FOR NEXT AGENT / HUMAN R5

Agent 只能準備與核對以下步驟，不能代替人執行最後一行 verify 或宣稱 R5 完成。

```bash
cd '/Users/tien/Documents/Codex 2'
git fetch origin
git status --short --branch
gh pr checks 2 --repo eason-tien/sage
gh pr diff 2 --repo eason-tien/sage --name-only
bash scripts/verify.sh runs/integrations/pr2-r5-docs-v0.1.16-attestation/r5/acceptance.txt
```

人類需親自閱讀 `verify-*.log`、PR2 Files changed、此文件的 TRAPS，確認退出碼為 0 且
沒有假綠，然後明確留下 R5 批准。只有這項證據成立後才可把 PR2 轉 Ready、合併、更新
About／Topics，最後從 `master` 建立 `v0.9.0` CLI Release。

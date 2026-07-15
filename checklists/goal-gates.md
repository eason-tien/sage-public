<!-- AGENT-FACING. Plan 確認後 MUST 六道閘齊備才放行 /goal。決定 /goal 是可控自動化 or 無人值守幻覺機。 -->
# goal-gates — 進 /goal 六道閘

## GATE-1 驗收 → 可機械判定完成條件 → R1
- [ ] 每條綁「命令 + 輸出/退出碼」，判 true/false
- [ ] 無「靠閱讀理解判定」的條件
- [ ] 含『貼真實命令輸出作為證據，別只說已通過』

## GATE-2 回滾與隔離 → R3
- [ ] git init + 乾淨起始 commit
- [ ] 在分支/worktree 跑，不直接動主幹

## GATE-3 上限與審計 → R4
- [ ] 設 --tokens 硬上限（CLI 無總量旗標時：以 max turns 兜底＋跑中盯用量，如 Claude Code 的 /cost）
- [ ] 條件內寫 max N turns（headless 例：`claude -p "…" --max-turns N`；旗標名以當日 CLI 文件為準）
- [ ] 輸出導日誌（每命令/每改動留痕；headless 例：`claude -p … --verbose --output-format stream-json > goal.log 2>&1`（stream-json 需配 --verbose），互動式外層 `| tee goal.log`）

## GATE-4 成功條件 + 失敗熔斷 並列 → P4
- [ ] 成功條件已定（GATE-1）
- [ ] 失敗熔斷：連續3輪同錯 / 遇規格未覆蓋分叉 / 需動禁區 / 連續2輪無進展 → 停下報告
- [ ] /goal 會「體面放棄並求助」，非硬撐燒完

## GATE-5 人類介入觸發信號
- [ ] 範圍超出原 Plan → 停下確認
- [ ] 借鏡與規格衝突 → 停下問
- [ ] 涉及權限/外發/刪除 → MUST 人確認 → R7
- [ ] 連續多輪同問題打轉 → 停下讓人看（可能規格矛盾）

## GATE-6 HANDOFF 為硬性驗收項
- [ ] 完成條件含「產出 HANDOFF.md，五區塊非空」
- [ ] 逼 Agent 趁記得上下文時固化交接

PASS: 全過 → 放行 /goal。跑完 → 進 final-acceptance.md。

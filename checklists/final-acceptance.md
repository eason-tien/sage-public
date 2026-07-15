<!-- AGENT-FACING. /goal 報完成 = 人最後把關的開始。核心：拉真實日誌 + 親跑驗證，辨真綠/假綠。 -->
# final-acceptance — 增量集成 + 最終驗收（Gate 3）

## A. 增量集成（走A多子任務）
- [ ] 每子 Goal 在自己分支/worktree 完成
- [ ] 集成在專門 integration 分支
- [ ] 逐個合入，每合一個就 commit
- [ ] 每合一個立即：跑集成測試（端到端串聯） / 重跑該模塊單元測試（防為兼容偷改致回歸） / 對照 CONTRACT.md 確認接口對得上
- [ ] 集成驗證掛 → git revert 回上一健康狀態
- [ ] 無循環依賴（工具查依賴圖）

## B. 走C產物併入 → R6
- [ ] 當外來模塊對待（沒遵守接縫契約）
- [ ] 額外驗接口與體系對得上

## C. 最終真實驗收（人親做，MUST NOT 交 Agent） → R5
- [ ] 拉真實執行日誌復核（非 Agent 自述結論）
- [ ] 親跑一遍驗收命令，確認退出碼/輸出符合預期
- [ ] 抽查 HANDOFF.md TRAPS 是否真實覆蓋已知坑（別讓它寫漂亮空洞交接）
- [ ] 確認驗收條件沒被鑽空子（無假綠）
- [ ] 驗收集已 `acceptance-lock lock acceptance.txt` 鎖定並 commit `.lock`；`verify` 報 exit 2（ACCEPTANCE TAMPERED）= 驗收集被改動 → 當假綠攻擊查清 → R9
- [ ] 成品以可看形式呈現給人：截圖/可點預覽/真實輸出片段，非純文字「已完成」 → R8
- [ ] 親跑時至少加一條清單外的即興抽查（lock 外、實作方事前不知——防「只針對已知清單優化」）

## D. 放行
- [ ] 真綠 → 合進 main（綠 ≠ 免 code review：合前仍過一眼 diff——綠只證明宣稱屬實，不證明軟件好）
- [ ] 假綠/有問題 → git 回滾，修條件或 Plan，重來
- [ ] 完成 → 寫 lessons.md 復盤（留任務倉）＋ 30 秒 `sage retro <任務名>`（落 sage 倉 retro/ 供週迭代彙整；提醒非強制）

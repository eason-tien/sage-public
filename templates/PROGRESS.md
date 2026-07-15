<!-- AGENT-FILLED. 中斷恢復錨點。執行中 Agent 每完成有意義小步即更新。 -->
# PROGRESS — [任務名]

NOTE: UltraCode（B/C）dynamic workflow 中斷會「從頭重跑」非接續 → B/C 要嘛一次跑完，要嘛限在「短到不怕重跑」的粒度。本機制主服務定位A（順序 /goal）。

## STATUS
- 更新時間：[timestamp]
- 整體進度：[X/Y 步]
- 最近 commit：[hash] — [描述]

## DONE
- [x] [步驟1]
- [x] [步驟2]

## DOING
- [ ] [當前步驟：做到哪 + 下一步]

## TODO
- [ ] [步驟3]
- [ ] [步驟4]

## BLOCKED
- [問題 + 是否已解決]

## RESUME（給接續 Agent/session）
- 讀本文件 + `git log` 了解進度
- 用 /resume 載回 session，MUST NOT 開新 session 從零
- 從「DOING」接續

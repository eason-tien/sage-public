# 星光小精靈 — SAGE Audit Contract

## Goal

製作一個無第三方 runtime dependency 的原創 Canvas 迷宮遊戲，並同時充當 SAGE
Evidence／R5 語義的 UI 審計 fixture。

## Functional acceptance

- 方向鍵、WASD 與觸控按鈕均可移動玩家。
- 牆壁與未開啟的出口 fail-closed。
- 收集星光加分；全部收集後出口才開啟。
- 紫色影子碰撞扣生命，生命歸零進入 lost；抵達已開出口進入 won。
- R／Enter／按鈕可重開。

## Audit invariants

- 遊戲核心與 Canvas renderer 分離，核心可由 Node deterministic tests 驗證。
- Audit snapshot 永遠保留 `r5HumanVerification=pending` 與
  `mergeAuthorized=false`。
- 公開 acceptance 必須鎖定；隱藏測試不得暴露給任何 benchmarked CLI。
- 自動測試綠只表示可交人做 R5，不得宣稱人類已驗收。

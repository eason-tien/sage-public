<!-- AGENT-FACING. OPT-IN 形态2 层。内核 KEEP-THIN 仍是默认。 -->
# workflows — 形态2 编排层（opt-in）

本目录是 SOP 的**可选**自动化层。内核（markdown 规则 + 薄脚本 + 人手动调用）仍是默认；本层只在主动调用时介入。它**有意识地放宽** DESIGN.md 非目标#1（不做自动编排程序）——作为 opt-in 层，不改默认形态。

## sop-run.js — 安全前半段编排器
由 Claude Code 用 Workflow 工具运行。它做 SOP 中**可自动化、可并行**的前半段：

  STEP 4 Plan → STEP 5 背靠背多审（N 个独立 reviewer）→ STEP 6 汇总分歧 → STEP 8 起草 /goal + 六道闸

跑完**停在人工闸**，交还一包「待你拍板」的产物（plan / reviews / 分歧 / goal 草案 / 闸口清单）。

### 它绝不做（守内核 R5/P3）
- 不写实现代码、不动 git、不跑 verify、不做任何不可逆操作。
- 不宣布「绿」。验收裁决权永远在你（人亲跑 verify）。

### 调用
```bash
# 先在受信任 launcher 中由 preflight 读取规则、prompts、spec、共享知识和 CodeGraph。
python3 workflows/sop-preflight.py \
  --sage-root <repo> \
  --task <任务名> \
  --spec <任务目录>/sop/prompts/01-spec.md \
  --knowledge <orchestrator-run>/SAGE_KNOWLEDGE.md \
  --reviewers 3 \
  --output <任务目录>/sop-bundle.json
```

然后读取该 JSON，把对象作为 `args.bundle` 传入：

```js
Workflow({ scriptPath: "<repo>/workflows/sop-run.js",
           args: { bundle: <sop-bundle.json 的 JSON 对象> } })
```

Workflow runtime 没有受支持的文件系统 primitive，因此 `sop-run.js` 不再直接信任 `sageRoot/specFile/spec`。runtime 会重算每份内嵌材料的 SHA-256、要求合法 `sourceHead`、拒绝超过 15 分钟或未来超过 5 分钟的 bundle，并从 task/spec 重新计算 Stitch 要求；UI／WPF 规格与 `stitchRequired` 不一致，或缺少 hash 正确的锁定 `STITCH_DESIGN.md`，都会在零 agent 状态返回 `{ hardStop: 'UNVERIFIED_INPUT_BUNDLE' }`。

这提供内容防误改、来源 SHA 绑定与短时重放限制，不等同有签章的来源认证：能控制 Workflow 入参的不受信任调用者仍可重造完整 bundle 与雜湊。`sop-preflight.py` 必须由受信任 launcher 在目标仓库执行；若以后需要跨信任边界，应再加入签章及独立信任根。

返回 `{ task, sourceHead, route, plan, reviews, reviewFailures, reviewersRequested, reviewersSucceeded, reviewerQuorum, agg, blockingCount, goal, humanGate, r5_human_verification, merge_authorized }`。reviewer quorum 固定为 2/2、2/3、3/4；不足即 `REVIEW_QUORUM_FAILED`。`blockingCount` 由脚本自己计算；GATE-5 必须是 `autoSatisfiable=false`，人工闸必须处理所有高严重度／blocking finding；LLM 无权声明 R5 或授权合并。

> 注:Workflow runtime 会把 `args` 以 JSON 字符串送达脚本，脚本会解析嵌套 bundle。plan／aggregate／goal-draft exception 会转换成结构化 hard-stop；schema 通过后仍会做非空、六闸唯一性、GATE-5 人工语义、正预算、HANDOFF.md 条件等验证，避免 `{}`、空数组或全自动闸门假成功。

### 边界
- author ≠ grader：起草 plan 的 agent 与审查的 reviewer 是不同 agent（P1）。
- **诚实声明（O-06）**：「只起草、不做不可逆操作」是**提示词层**的纪律,不是机制——harness 并未收走子 agent 的工具。把这层当「留痕的约定」用;机械闸在 verify/lock,不在这里。
- 它是 Claude Code Workflow 脚本，只在 Claude Code 内运行，不是独立 CLI。
- 执行（写代码）与最终验收仍由你按内核流程走。

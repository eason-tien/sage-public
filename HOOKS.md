<!-- AGENT-FACING. OPT-IN 强制层。R9 的防篡改已在 verify.* 内强制；本文件是额外的 Claude Code Stop-hook。 -->
# HOOKS — 可选的 Claude Code 强制层（opt-in）

R9 的防篡改闸已经在 `verify.*` 里强制（验收集被改 → 拒认证 exit 2）。本文件再给一个**可选**的 Claude Code Stop hook：让 agent 每次停止时自动跑 `acceptance-lock check`。验收集被改时，第一次会挡住停止并把原因回灌给 agent；若下一次 Stop 仍失败，hook 会停止重试并要求人工处理，避免 `stop_hook_active` 递归造成无限循环。

> 默认不装。装了会影响该 project（或全局）所有会话——你自己决定，不需要时删掉这段 settings 即可，脚本本身不依赖 hook。

## 安装（project 级）

先把 `SAGE_ROOT` 设成目前安装位置；换机只改环境变量，不改 hook。`SAGE_ACCEPTANCE_FILE` 可省略，默认是当前任务目录下的 `acceptance.txt`。

```powershell
$env:SAGE_ROOT = "C:\path\to\sage"
$env:SAGE_ACCEPTANCE_FILE = "acceptance.txt"
```

Windows 的 `.claude/settings.json`：

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python \"%SAGE_ROOT%\\scripts\\claude-stop-hook.py\""
          }
        ]
      }
    ]
  }
}
```

macOS/Linux 先 `export SAGE_ROOT=/path/to/sage`，再使用同样结构，但 command 改为：

```json
"command": "python3 \"$SAGE_ROOT/scripts/claude-stop-hook.py\""
```

Claude Code 会把 Stop 事件 JSON 从 stdin 传给脚本；不要在 command 后自行追加或替换 stdin。脚本会验证 `hook_event_name`、`cwd` 和布尔值 `stop_hook_active`，然后在事件的 `cwd` 执行验收锁检查。

行为如下：

- 锁正常：exit 0，允许正常停止。
- 第一次检查失败，且 `stop_hook_active=false`：诊断写到 stderr 后 exit 2，阻止本次 Stop 并让 Claude 继续处理。
- 再次停止仍失败，且 `stop_hook_active=true`：exit 0 并输出 `continue:false` JSON，终止自动重试、显示 `stopReason`，要求人工介入。
- 输入不完整、路径不安全或检查器不可用：直接要求人工介入，不会把自动检查误报成成功。

上述行为依照 Claude Code 官方的 [hooks 事件与 Stop 输入约定](https://code.claude.com/docs/en/hooks)。

## 注意

- hook 在事件提供的当前工作目录运行，验收文件只能使用安全的相对路径；请在任务根目录启动会话。
- 它是**强制层不是裁判**：只确认「验收集没被改」。自动化永远保持 `r5_human_verification=pending`、`merge_authorized=false`；最终 R5 仍必须由人执行并绑定到确切 commit SHA。
- 安装后先在测试项目中修改一次 acceptance，确认第一次 Stop 被挡、第二次不会无限循环。

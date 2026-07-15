# 星光小精靈

原創、零 runtime dependency 的 Canvas 小遊戲，也是 workflow-lab 的輕量 UI
及端到端審計 fixture。

```bash
cd examples/sprite-audit-game
python3 -m http.server 8080
```

開啟 `http://localhost:8080`。公開測試：

```bash
npm test
```

完整審計由根目錄 `python3 tools/audit_sprite_game.py` 執行；隱藏測試只在實作者
完成後由 auditor 使用，不得提供給 benchmarked CLI。

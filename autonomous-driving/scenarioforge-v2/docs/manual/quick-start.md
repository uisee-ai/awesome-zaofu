# 快速开始

在 Linux x86_64 上进入本项目目录，依次执行：

```bash
uv sync --frozen
uv run python -m metadrive.pull_asset
uv run scenarioforge web --port 8000
```

浏览器打开 <http://127.0.0.1:8000/>，然后：

1. 选择 `Built-in templates`。
2. 选择 `Lead Vehicle Emergency Braking`。
3. 点击 `Run selected scenario`。
4. 等待 Worker 结束，在 `Run evidence` 查看终态和指标。
5. 在 `Trajectory player` 播放、拖动时间轴并跳转关键事件。

停止服务时回到终端按 `Ctrl+C`。首次运行前必须完成 MetaDrive 官方资产下载；完整说明
见[部署与安装](deployment.md)，三种创作方式见[用户手册](user-guide.md)。

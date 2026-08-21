# 常见问题

## 页面打不开

确认启动终端没有退出，并检查端口：

```bash
curl -fsS http://127.0.0.1:8000/api/session
```

若端口被占用，改用 `--port 8001`。不要为解决端口问题把服务暴露到 `0.0.0.0`。

## Worker is running 很久

首次运行可能需要初始化 MetaDrive/SMARTS/SUMO。等待页面终态，同时查看启动终端是否有
依赖、资源或场景错误。默认单次超时为 120 秒，可用 `web --timeout-seconds` 调整；不应
无限放大超时来掩盖死锁。

如果错误提示 `MetaDrive asset version file is missing`，先停止服务并执行：

```bash
uv run python -m metadrive.pull_asset
```

资产下载是一次性的安装步骤，不应由运行中的 Worker 自动完成。

## 自然语言提示不受支持

离线 Provider 只识别已登记 benchmark intent。请明确包含“前车急刹”“行人”“闯红灯”
“无保护左转”“竞争换道”或“高速汇入”等关键词，或直接切换到严格 JSON/模板。

## SMARTS/SUMO 启动失败

确认完整安装或 simulation 组已安装：

```bash
uv sync --frozen --group simulation
uv run python -c "import smarts; print('SMARTS import OK')"
uv run sumo --version
```

如果系统不允许创建所需进程/命名空间，应在受支持 Linux 环境运行；不要通过关闭所有
隔离或使用不受信任输入来绕过限制。

## 3D 回放黑屏或不动

先确认运行已经产生可播放轨迹，而不是仍在 `running` 或只有失败诊断。再检查浏览器是否
支持 WebGL、控制台是否加载本地 Three.js，以及时间轴是否位于有效帧。服务 CSP 禁止从
CDN 动态加载脚本，因此 vendor 文件必须保留。

## 测试导入 `tests` 失败

从项目根目录运行测试，不要进入 `tests/` 子目录。发布快照包含 `tests/__init__.py`，如果
本地被删除，请恢复后重新执行 `uv run pytest -q`。

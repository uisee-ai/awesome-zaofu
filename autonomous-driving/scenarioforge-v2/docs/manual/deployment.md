# 部署与安装

## 1. 支持环境

- Linux x86_64
- Python 3.11.15（项目使用精确版本约束）
- 可访问 PyPI 的网络，仅安装阶段需要
- 建议至少 8 GiB 内存、5 GiB 可用磁盘
- GPU 非必需；默认使用 headless 仿真

Windows 与 macOS 可自行尝试，但不属于当前正式验证范围。

## 2. 安装 uv

优先按 uv 官方文档安装。安装后确认：

```bash
uv --version
```

## 3. 完整安装

在 `autonomous-driving/scenarioforge-v2` 目录执行：

```bash
uv sync --frozen
uv run python -m metadrive.pull_asset
```

第一条命令按 `uv.lock` 安装开发、Web、浏览器测试和双仿真后端依赖。MetaDrive 0.4.3
将引擎资产单独发布，第二条命令从 MetaDrive 官方 release 下载匹配资产；缺少
`metadrive/assets/version.txt` 时 ScenarioForge 会 fail closed。首次执行下载量较大。

如需运行 Playwright 端到端测试，再安装 Chromium：

```bash
uv run playwright install chromium
```

部分 Linux 发行版缺少浏览器系统库时，可参考 Playwright 官方安装说明补齐依赖；不要在
不了解影响的情况下直接运行带 root 权限的自动安装命令。

## 4. 最小安装

只使用核心 CLI 与 MetaDrive、暂不运行 Web/SMARTS/浏览器测试时：

```bash
uv sync --frozen --no-default-groups
uv run python -m metadrive.pull_asset
```

只增加 Web 服务：

```bash
uv sync --frozen --no-default-groups --group web
```

SMARTS/SUMO 能力需要 `simulation` 组：

```bash
uv sync --frozen --no-default-groups --group web --group simulation
```

## 5. 启动服务

```bash
uv run scenarioforge web --port 8000
```

打开 <http://127.0.0.1:8000/>。默认运行产物存储在当前目录的
`.scenarioforge-runs/`，服务只绑定 `127.0.0.1`。

指定独立工作区：

```bash
uv run scenarioforge \
  --project-root "$PWD" \
  --workspace "$PWD/.scenarioforge-demo-runs" \
  web --port 8000
```

## 6. 停止与重启

在启动服务的终端按 `Ctrl+C`。服务会先请求中断当前 Worker，再等待终态发布。不要在
运行写入过程中直接删除工作区。重新启动同一命令即可读取已发布结果。

## 7. 网络边界

本项目没有生产级鉴权，不应通过 `0.0.0.0`、反向代理或端口映射暴露到局域网/公网。
若需要多人或远程部署，应先独立完成身份认证、CSRF、限流、审计、隔离与数据保留设计。

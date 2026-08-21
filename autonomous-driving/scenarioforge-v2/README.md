# ScenarioForge v2

ScenarioForge v2 是一个本地自动驾驶场景创作、仿真执行和三维轨迹回放工作台。用户可
从内置模板、严格 JSON 或受支持的自然语言意图创建场景，经校验后交给 MetaDrive 或
SMARTS 执行，并在同一页面查看终态、关键事件、指标和可跟车的 3D 回放。

本项目是 [Awesome ZaoFu](https://github.com/uisee-ai/awesome-zaofu) 的独立案例快照。
它用于研究、评测和演示，不是量产仿真平台、真实车辆控制器或安全认证产品。

## 主要能力

- 一个统一的 Scenario Studio：自然语言、JSON 和内置模板共用校验、执行与回放链路。
- MetaDrive 场景：前车急刹、施工并道、危险切入、高速汇入、无保护左转。
- SMARTS 场景：高速汇入、竞争换道、横向闯红灯、行人红灯横穿、无保护左转。
- 严格场景合同：版本化 ScenarioSpec、能力预检、不可变 revision 和运行授权。
- 隔离执行：single-run worker、超时、终态发布、运行产物和复现比较。
- 3D 回放：道路、车辆、行人、信号灯、事件标记、指标、时间轴和跟车视角。
- CLI 与本地 Web API，可用于编译、单次运行、三次复现和实验控制。

## 五分钟启动

正式支持环境为 Linux x86_64、Python 3.11.15。先安装
[uv](https://docs.astral.sh/uv/)，然后在本目录执行：

```bash
uv sync --frozen
uv run python -m metadrive.pull_asset
uv run scenarioforge web --port 8000
```

浏览器打开 <http://127.0.0.1:8000/>。服务只监听本机回环地址。

MetaDrive 0.4.3 把版本化引擎资产与 Python 包分开发布，因此首次安装必须显式执行
`metadrive.pull_asset`；ScenarioForge 会在资产缺失时拒绝运行，而不会在 Worker 内静默
联网下载。首次安装依赖和资产的耗时取决于网络环境。
若只想运行 MetaDrive，不使用 SMARTS 或浏览器测试，请参阅
[部署与安装](docs/manual/deployment.md) 的最小安装方式。

## 第一次使用

1. 在 Scenario Studio 顶部选择 `Built-in templates`。
2. 选择一个 MetaDrive 或 SMARTS 场景，阅读参与者与目标说明。
3. 点击 `Run selected scenario`，等待 Worker 产生终态证据。
4. 在 `Run evidence` 查看场景、后端、结果与关键指标。
5. 在 `Trajectory player` 点击播放，拖动时间轴或跳转到关键事件。
6. 再尝试 `Natural language` 或 `JSON`，生成/粘贴草稿后完成预检与确认。

完整操作见[中文用户手册](docs/manual/user-guide.md)。

## CLI 示例

```bash
# 校验严格 JSON
uv run scenarioforge validate --json examples/p0c/brake_lead.json

# 编译场景
uv run scenarioforge compile examples/p0a/brake_lead.json

# 单次隔离执行
uv run scenarioforge run examples/p0a/brake_lead.json \
  --run-id demo-001 --attempt-id attempt-001

# 三次重新执行并比较
uv run scenarioforge reproduce examples/p0a/brake_lead.json \
  --comparison-id demo-repro --run-id-prefix demo-repro-run
```

CLI 的工作目录默认写入 `.scenarioforge-runs/`，可通过全局参数 `--workspace` 修改。

## 验证

```bash
uv lock --check
uv run pytest -q
```

真实仿真和浏览器用例会启动子进程，耗时明显高于纯合同测试。详细分层验证方式见
[开发与验证](docs/manual/development.md)。

## 文档

- [快速开始](docs/manual/quick-start.md)
- [部署与安装](docs/manual/deployment.md)
- [用户手册](docs/manual/user-guide.md)
- [CLI 与自动化](docs/manual/cli.md)
- [架构说明](docs/manual/architecture.md)
- [常见问题](docs/manual/troubleshooting.md)
- [ZaoFu 交付案例](CASE.md)
- [第三方软件与素材声明](THIRD_PARTY_NOTICES.md)
- [公开发布清单](docs/release/publication-checklist.md)

## 安全、隐私与许可证

ScenarioForge v2 默认是本机单用户工具，只接受受约束的场景数据，不应执行第三方代码。
不要把服务暴露到公网，也不要把密钥、真实车辆数据、客户资产或个人信息放进场景。

原创源码和文档采用 Apache License 2.0。Three.js、SUMO 生成路网及外部运行依赖保留
各自许可证，详见 [`LICENSE`](LICENSE)、[`NOTICE`](NOTICE) 和
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

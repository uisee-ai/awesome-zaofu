# HighwayPilot Lab 案例材料

这是 HighwayPilot Lab 当前工作树的独立 source-only 案例快照，由真实源码、配置、
测试和文档组成。

## 来源与版本边界

- 本地项目包版本：`0.1.0`（见根目录 `pyproject.toml` 与 `package.json`）。
- 本地源码基线：`e3d2bcc9feea2ce6b92b1ed92651e1aaea6c7330`。
- 材料生成日期：2026-09-03；生成时工作树包含未提交改动，因此本材料不能冒充一个干净的发布 commit。

本目录包含当前项目已经存在的源码、配置、schema、模型合同和测试入口。
功能状态以 [`CASE.md`](CASE.md) 和随案例快照保存的
[`docs/reference/prd-acceptance-matrix.md`](docs/reference/prd-acceptance-matrix.md) 为准；没有重新运行
的测试不会被本目录重新宣称为通过。

## 产品定位

HighwayPilot Lab 是一个本地三维驾驶决策实验室：Python 服务持有仿真、控制、决策、
奖励和 Episode 的唯一权威状态，TypeScript/Three.js 负责交互、插值和渲染。当前实现
围绕 HighwayEnv 的 `construction-v0` 施工并道场景，提供人工、随机、规则和 ONNX
策略入口，以及策略比较、按 Seed 配对评估和 Episode 回放。

该项目面向本地研究、评测和演示，不是量产仿真平台、真实车辆控制器或安全认证产品。

## 五分钟启动

在本案例根目录执行（依赖安装会修改本机环境）：

```bash
uv sync --frozen --group dev
npm ci
PATH="$PWD/.venv/bin:$PATH" HIGHWAYPILOT_PORT=8000 ./scripts/start-demo.sh
```

浏览器打开 `http://127.0.0.1:8000/`。服务入口固定使用 loopback；停止服务使用
`Ctrl-C`。`start-demo.sh` 会在源码或 Web 资源晚于发布装配时重新运行装配脚本。

说明：本快照排除了规划投影、`dist/` 和运行态
`artifacts/`。因此上面的演示命令适用于保留完整项目级 release 输入的工作树；从 GitHub
单独下载本案例后，需先按发布清单准备装配输入，不能把缺少这些输入视为源码缺陷。

## 材料索引

- [`CASE.md`](CASE.md)：案例定位、实现路径、状态边界和发布限制。
- [`case.yaml`](case.yaml)：机器可读案例元数据。
- [`docs/manual/`](docs/manual/quick-start.md)：安装、用户操作、架构、部署、开发和故障排查。
- [`docs/reference/`](docs/reference/configuration-and-schemas.md)：配置、schema、来源清单和验收矩阵。
- [`source-manifest.json`](source-manifest.json)：采集时关键来源文件的 SHA-256 清单。
- [`docs/release/publication-checklist.md`](docs/release/publication-checklist.md)：source-only 发布保留/排除清单。
- [`NOTICE`](NOTICE)：本案例的简短版权和第三方边界声明。
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)：依赖和许可证资料的来源说明。

## 不随材料包复制的内容

`.zf-highwaypilot-lab-v7`、`.highwaypilot`、`artifacts/`、`diagnostics/`、构建缓存、
浏览器 trace、录屏和其他运行态产物不属于 source-only 材料。它们可能包含本机状态、
临时证据或大型媒体，不应被误认为产品源码或稳定发布输入。

# ScenarioForge Case

## 案例定位

ScenarioForge 是一个本地优先的自动驾驶场景仿真工作台。它把场景文档编译为
可执行计划，在隔离进程中运行 MetaDrive，并把轨迹、事件、安全指标和
Provider 信息封装为可校验的密封 bundle，供 Web 精确回放和 baseline/candidate
比较使用。

## ZaoFu 交付路径

1. PRD 阶段建立 Scenario Spec、编译器、运行器、Oracle、CLI/Web 和离线安全边界。
2. IssueFlow 补齐紧急制动事件、多 Actor 证据、真实浏览器回放与回归闭环。
3. Verify/Judge 绑定代码、测试、截图、轨迹和 SHA-256 证据，而不是只检查任务状态。

需求与过程入口：

- [`docs/prd/scenarioforge-metadrive-p0-r1.json`](docs/prd/scenarioforge-metadrive-p0-r1.json)
- [`docs/issues/scenarioforge-p0-product-completion.md`](docs/issues/scenarioforge-p0-product-completion.md)
- [`docs/issues/scenarioforge-showcase-closure-v4.md`](docs/issues/scenarioforge-showcase-closure-v4.md)
- [`docs/release/`](docs/release/)（公开发布说明与最小验收证据）

## 已验证能力

- JSON/YAML 场景校验、canonical digest 与受限编译。
- 多 seed 异步运行、资源限制、取消和失败恢复。
- 真实 MetaDrive 紧急制动场景与碰撞证据。
- 密封 replay bundle、精确回放校验、baseline/candidate 差异报告。
- React/Three.js 回放工作台、CLI、FastAPI 和浏览器 E2E。
- 依赖锁定、离线资产校验、SBOM、威胁模型和非生产安全声明。

## 快照与打包

- 源项目：ScenarioForge showcase 工作树
- 源 ref：`dev`
- 源 commit：`38548682e4bb0d3b98e234a92c8482dda398b5b5`
- 打包方式：`git archive` 后转为 source-only 案例。
- 未复制：Git 历史、`.zf-*`、本地报告导出、MP4 和 `web/dist` 编译产物。
- 保留：源码、锁文件、测试、PRD/Issue、发布文档和密封运行证据。

原仓库将 `web/dist` 视为发布制品，因此其中两项 release-hygiene 测试要求已提交
dist。Awesome 快照不提交 Node 编译产物；运行前执行 `npm --prefix web ci` 和
`npm --prefix web run build`。产品与开发说明见 [`README.md`](README.md)。

## 许可证与安全

该项目当前使用 [`LICENSE`](LICENSE) 中的 source license notice，并非宽松开源
许可证。复制到本仓库不产生额外授权。MetaDrive assets 不随案例分发；参见
[`NOTICE`](NOTICE) 和 [`docs/release/non-production-safety.md`](docs/release/non-production-safety.md)。

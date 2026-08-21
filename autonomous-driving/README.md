# Autonomous Driving

自动驾驶领域的 ZaoFu 完整项目案例。当前案例覆盖四条互补链路：

| 项目 | 主要问题 | 产品形态 | ZaoFu 路径 | 验证概况 |
| --- | --- | --- | --- | --- |
| [ScenarioForge](scenarioforge/CASE.md) | 如何编写、执行和精确回放可版本化仿真场景 | Python + React 本地仿真工作台 | PRD 构建后通过 IssueFlow 补齐紧急制动语义和交付闭环 | 真实 MetaDrive 运行、Chromium E2E、SHA-256 可校验运行证据 |
| [Alpamayo Web Studio](alpamayo-web-studio/CASE.md) | 如何管理道路场景并完成视觉推理、轨迹与回归评测 | Next.js + FastAPI 推理工作台 | PRD V4 多 Agent 长周期构建与产品硬化 | 已提交产品快照、mock/Provider 合同与产品测试 |
| [CAN Lab](canlab/CASE.md) | 如何离线浏览 DBC、确定性回放 CAN 帧并追溯解码过程 | React + TypeScript 浏览器实验室 | 多视角 PRD、实现、验证和发布证据收口 | 确定性测试、Chromium E2E、被动安全边界 |
| [Sensor Workbench](sensor-workbench/CASE.md) | 如何在本地浏览 nuScenes/OpenLane 多模态数据并完成标注审核 | React + TypeScript 本地数据工作台 | 双 Adapter、审核契约、数据边界和浏览器验证收口 | 63 个单测、合成 Chromium E2E、只读数据根边界 |

## 分类边界

该目录按业务领域划分，而不是按框架或工作流划分。一个项目即使同时展示
`prd`、`issue`、多 Agent、前后端和真实 E2E，也只在这里保留一份源码。

所有案例仅用于研究、评测和演示，不得直接控制车辆，也不构成安全认证。

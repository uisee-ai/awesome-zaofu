# Awesome ZaoFu

`awesome-zaofu` 收录由 [ZaoFu](https://github.com/uisee-ai/zaofu) 多 Agent
工作流交付的可运行产品案例。仓库按业务领域组织，每个项目仅保留一份源码，
并通过 `case.yaml` 描述工作流、技术栈和验证范围。

这些案例聚焦真实领域问题，参考相关 GitHub 开源项目的应用场景、领域模型与
工程实践，用于展示 ZaoFu 如何将需求讨论、PRD、工程实现和验证证据转化为
可运行、可复核的产品交付，而不只是生成代码片段。项目可按需使用经过来源核验
的开源数据集、仿真环境和测试语料。每个项目的 `README.md` 说明产品目的、参考
项目与数据来源，`CASE.md` 和 `case.yaml` 记录交付路径、验证结果与快照来源。

## 项目

| 分类 | 项目 | 产品入口 | 用户指南 | 核心能力 |
| --- | --- | --- | --- | --- |
| [Autonomous Driving](autonomous-driving/) | [ScenarioForge](autonomous-driving/scenarioforge/) | [README](autonomous-driving/scenarioforge/README.md) | [User Guide](autonomous-driving/scenarioforge/docs/manual/user-guide.md) | 版本化场景编排、MetaDrive 批量仿真、精确回放与回归对比 |
| [Autonomous Driving](autonomous-driving/) | [Alpamayo Web Studio](autonomous-driving/alpamayo-web-studio/) | [README](autonomous-driving/alpamayo-web-studio/README.md) | [User Guide](autonomous-driving/alpamayo-web-studio/docs/manual/user-guide.md) | 道路场景管理、视觉推理、轨迹生成与回归评测 |
| [Autonomous Driving](autonomous-driving/) | [CAN Lab](autonomous-driving/canlab/) | [README](autonomous-driving/canlab/README.md) | [User Guide](autonomous-driving/canlab/docs/manual/user-guide.md) | DBC 浏览、确定性 CAN 回放、可追溯解码与健康分析 |

每个项目的文档职责固定为：

- `README.md`：产品定位、安装、启动和开发验证。
- `docs/manual/user-guide.md`：面向使用者的操作流程。
- `CASE.md`：ZaoFu 交付路径、证据等级和快照边界。
- `case.yaml`：供索引与自动化消费的机器可读元数据。

## 收录标准

- 提供可阅读的需求或目标基线，而不只是代码片段。
- 提供产品源码、测试和最小运行说明。
- 标明被复制的源提交以及任何 source-only 打包差异。
- 区分 mock、真实 Provider、真实浏览器和真实领域运行证据。
- 不收录 `.zf-*` 运行状态、依赖目录、编译缓存、密钥、归档包或本地音视频成片。
- 保留运行所需 fixture、被文档引用的截图，以及能够复核交付结论的最小证据。
- 根许可证适用于仓库发布者有权授权的内容；项目内许可证、NOTICE 和第三方声明优先。

## 目录约定

```text
<domain>/
  README.md
  <project>/
    CASE.md
    case.yaml
    ...project source...
```

横向标签包括 `prd`、`issue`、`real-e2e`、`sealed-evidence`、
`full-stack` 等，但不会为这些标签重复复制项目。

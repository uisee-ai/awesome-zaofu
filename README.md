# Awesome ZaoFu

`awesome-zaofu` 收录由 [ZaoFu](https://github.com/uisee-ai/zaofu) 多 Agent
工作流交付并经过验证的完整产品案例。仓库按业务领域分类；每个项目只保留一个
源码目录，工作流类型、技术栈和验证等级通过 `case.yaml` 表达。

这些项目用于回答一个具体问题：ZaoFu 能否把需求讨论、PRD、实现、验证和证据
收口连续交付为可运行产品，而不只是生成代码片段。案例选题来自真实领域问题，
产品代码由 ZaoFu 工作流依据各项目 PRD 实现；外部开源项目按实际角色作为运行
依赖、领域参考或兼容性语料，并不自动意味着 fork 或源码派生。每个项目 README
说明开发目的与上游关系，`CASE.md` 和 `case.yaml` 记录交付与快照来源。

## 项目

| 分类 | 项目 | 产品入口 | 用户指南 | 验证等级 |
| --- | --- | --- | --- | --- |
| [Autonomous Driving](autonomous-driving/) | [ScenarioForge](autonomous-driving/scenarioforge/) | [README](autonomous-driving/scenarioforge/README.md) | [User Guide](autonomous-driving/scenarioforge/docs/manual/user-guide.md) | 真实 MetaDrive、浏览器 E2E、密封证据 |
| [Autonomous Driving](autonomous-driving/) | [Alpamayo Web Studio](autonomous-driving/alpamayo-web-studio/) | [README](autonomous-driving/alpamayo-web-studio/README.md) | [User Guide](autonomous-driving/alpamayo-web-studio/docs/manual/user-guide.md) | Mock 产品闭环、Provider 合同、前后端测试 |
| [Autonomous Driving](autonomous-driving/) | [CAN Lab](autonomous-driving/canlab/) | [README](autonomous-driving/canlab/README.md) | [User Guide](autonomous-driving/canlab/docs/manual/user-guide.md) | 确定性回放、浏览器 E2E、发布证据 |

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

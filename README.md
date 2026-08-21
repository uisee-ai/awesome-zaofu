# Awesome ZaoFu

`awesome-zaofu` 收录由 [ZaoFu](https://github.com/uisee-ai/zaofu) 交付的可运行
产品案例，用于展示和评测 multi-agent + long-horizon 场景下的工程交付能力。
仓库按业务领域组织，每个项目仅保留一份源码，并通过 `case.yaml` 描述工作流、
技术栈和验证范围。

这些案例聚焦真实领域问题，用于展示 ZaoFu 如何将需求讨论、PRD、工程实现和
验证证据持续收口为可运行、可复核的产品交付，而不只是生成代码片段。每个项目的
`README.md` 说明产品目的、参考项目与数据来源，`CASE.md` 和 `case.yaml` 记录
交付路径、验证结果与快照来源。

> [!IMPORTANT]
> 本仓库是 ZaoFu multi-agent + long-horizon 工程能力的公开展示与评测集合。
> 所收录项目均为独立构建的演示或参考实现，不代表 Uisee Technologies 的量产
> 系统、生产部署、商业产品、客户项目、产品路线或安全认证。除非项目文档另有
> 明确说明，案例不得用于生产车辆控制或作为安全决策依据。

## 项目

| 项目 | 产品定位 | 状态 | 快速开始 | 交付证据 | 许可证 |
| --- | --- | --- | --- | --- | --- |
| [ScenarioForge](autonomous-driving/scenarioforge/) | 版本化场景编排、MetaDrive 批量仿真、精确回放与回归对比 | Verified showcase | [README](autonomous-driving/scenarioforge/README.md) | [CASE](autonomous-driving/scenarioforge/CASE.md) | [Project license](autonomous-driving/scenarioforge/LICENSE) |
| [Alpamayo Web Studio](autonomous-driving/alpamayo-web-studio/) | 道路场景管理、视觉推理、轨迹生成与回归评测 | Product snapshot | [README](autonomous-driving/alpamayo-web-studio/README.md) | [CASE](autonomous-driving/alpamayo-web-studio/CASE.md) | [Apache-2.0](autonomous-driving/alpamayo-web-studio/LICENSE) |
| [CAN Lab](autonomous-driving/canlab/) | DBC 浏览、确定性 CAN 回放、可追溯解码与健康分析 | Verified showcase | [README](autonomous-driving/canlab/README.md) | [CASE](autonomous-driving/canlab/CASE.md) | [Apache-2.0](LICENSE) + fixture notices |
| [Sensor Workbench](autonomous-driving/sensor-workbench/) | nuScenes/OpenLane 多模态浏览、坐标投影与标注审核 | Product snapshot | [README](autonomous-driving/sensor-workbench/README.md) | [CASE](autonomous-driving/sensor-workbench/CASE.md) | [Apache-2.0](autonomous-driving/sensor-workbench/LICENSE) |

每个项目的文档职责固定为：

- `README.md`：产品定位、安装、启动和开发验证。
- `docs/manual/user-guide.md`：面向使用者的操作流程。
- `CASE.md`：ZaoFu 交付路径、证据等级和快照边界。
- `case.yaml`：供索引与自动化消费的机器可读元数据。

## 参考项目与第三方材料

- [MetaDrive](https://github.com/metadriverse/metadrive) 是 ScenarioForge 使用的外部
  仿真运行时，也为其场景仿真设计提供参考。本仓库不打包 MetaDrive 源码和资产归档。
- [openDBC](https://github.com/commaai/opendbc) 和
  [cantools](https://github.com/cantools/cantools) 为 CAN Lab 提供经过版本锁定并保留
  原始许可声明的 DBC 测试语料。
- NVIDIA Alpamayo 是 Alpamayo Web Studio 集成的外部模型。本仓库不分发模型权重，
  模型及其权重仍适用 NVIDIA 的相关许可条款。

各项目与上述第三方项目不存在隶属关系，也不代表获得其官方认可或背书。第三方代码、
模型、数据、商标和资产仍适用各自的原始许可证及使用条款；具体来源和使用边界见项目级
`README.md`、`LICENSE`、`NOTICE` 或来源清单。

## 许可证

根目录 [Apache-2.0](LICENSE) 许可证仅适用于仓库发布者拥有或有权按该条款授权的内容。
项目级 `LICENSE`、`NOTICE` 及第三方许可证优先适用于各自对应的源码、模型、数据、素材
和配置。本仓库不额外授予任何第三方商标、模型权重、数据集或资产的使用权。

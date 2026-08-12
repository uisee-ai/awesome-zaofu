# CAN Lab 介绍视频脚本与交付说明

## 成片目标

- 主成片：16:9，3840 × 2160；兼容版：1920 × 1080
- 语言：中文旁白 + 中文字幕
- 字幕：统一深色、无阴影，固定在独立的底部安全区，不覆盖页面内容
- 内容：真实 Playwright 4K 页面状态、ZaoFu Loop 实图、可复核工程指标
- 边界：CAN Lab 使用内置合成 DBC 与确定性日志，离线、只接收，不连接真实车辆或发送 CAN 报文
- 归因：CanLab 是产品案例；需求理解、多 Agent 执行、rework 与证据闭环属于 ZaoFu 的交付能力

## 成片文件

- `artifacts/showcase/canlab-introduction-zh-4k.mp4`
- `artifacts/showcase/canlab-introduction-zh-1080p.mp4`
- `artifacts/showcase/canlab-introduction-poster.png`

## 旁白

这是 CAN Lab，一个由 ZaoFu 多智能体工作流，从产品需求一路实现并验证的浏览器内 CAN 分析工具。

CAN 数据通常以十六进制帧出现。没有 DBC 定义和可追溯的解码链，工程师很难判断一个比特代表转速、车速，还是控制状态。

CAN Lab 把这条链路放进浏览器。本地加载合成 DBC 和确定性 CAN 日志，先核验 SHA-256，再开放工作区。它完全离线、只接收、不连接真实车辆，也不会发送 CAN 报文。

在 DBC Explorer 中搜索 EngineRpm，可以看到它位于 0x100 Powertrain 消息，占用第 0 到 15 位，采用 Intel 字节序，缩放系数是 0.25。

单步回放会原子处理同一时间戳的帧。选择序号 0 之后，Decode Trace 将原始字节、位域、整数、公式和物理值逐级展开：3168 乘以 0.25，得到每分钟 792 转。

跳转到 260 万微秒，虚拟车辆按照事件历史重建仪表、六类趋势和报文健康状态。因此播放速度或电脑抖动，不会改变同一事件时间点的结果。

这个案例本身也由 ZaoFu 留下可审计证据。成功的核心 PRD 工作流历时 8 小时 34 分 04 秒，经过计划、任务图、实现、验证和裁决。项目累计启用 11 个计费 Agent 实例，消耗 2.1916 亿 Tokens，成本 670.17 美元。当前源码、工具和测试共 44 个文件、8246 行，66 项测试通过。

结果不是一个无法解释的演示，而是一个知道数据从哪里来、如何计算、如何失败关闭、又如何被验证的工程交付。CanLab 是产品案例，ZaoFu 是把需求变成可运行、可追溯、可复验交付的多智能体工程系统。

## 指标口径

| 指标 | 数值 | 口径 / 来源 |
| --- | ---: | --- |
| 代码量 | 8,246 行 / 44 文件 | `src`、`tools`、`tests` 的物理行数 |
| 自动测试 | 66 / 66 | 当前项目测试套件 |
| 核心 PRD workflow | 8:34:04 | `workflow-75682a05ea2f2140` 的 `run.goal.started` 到 `run.goal.completed` |
| Agent | 11 | `zf cost --by-instance --json` 中有计费记录的 Agent instance |
| Token | 219,155,250 | 项目累计输入 + 输出 Tokens |
| 成本 | $670.172802 | 项目累计成本，不是单次 workflow 成本 |

## 镜头顺序

1. 标题与产品定义。
2. CAN 原始帧的理解门槛。
3. 真实工作区与完整性校验。
4. 搜索并查看 `EngineRpm` DBC 定义。
5. 单步回放、选择帧、查看完整 Decode Trace。
6. Seek 到 `2,600,000 µs`，查看虚拟车辆和 Message Health。
7. ZaoFu Loop 截图与真实运行指标。
8. 可运行、可追溯、可复验的交付结语。

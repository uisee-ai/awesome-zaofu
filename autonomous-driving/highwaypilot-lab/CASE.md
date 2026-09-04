# HighwayPilot Lab Case

## 案例定位

本案例展示如何把 HighwayEnv 施工并道实验组织成一个可核验的本地产品：同一份配置
进入 Python 仿真 authority、Gymnasium 包装器、策略比较/评估和 WebSocket HMI；Episode
记录可进入 Library 并回放。案例材料由产品源码、配置、测试和发布边界组成。

## 交付路径

1. 配置由 `schemas/construction-config/v1.schema.json` 和
   `src/highwaypilot_lab/config/parser.py` 约束，并由四份 `configs/presets/*-v1.json`
   提供实际预设。
2. `src/highwaypilot_lab/simulation/authority.py` 持有仿真事实状态；
   `environment.py` 适配 HighwayEnv 并计算碰撞、并道、速度、车道、TTC 等状态与奖励。
3. `src/highwaypilot_lab/simulation/gym_env.py` 注册 Gymnasium `construction-v0`，提供
   `reset`、`step`、`close`、离散五动作和固定形状 observation。
4. `src/highwaypilot_lab/protocol/messages.py`、`session/core.py` 和
   `api/server.py` 组成版本化 WebSocket/API 会话边界；Three.js 只渲染后端快照。
5. `strategies/policy.py` 提供 `manual`、`random`、`qualified_rule` 和
   `construction_dqn_onnx`；`comparison.py` 做同配置/Seed 的单次比较，`evaluation.py`
   对不重复 Seed 做配对统计并计算比例与区间。
6. `episodes/replay.py` 与 `episodes/library.py` 负责 Episode 校验、持久化、保存和回放。

## 当前状态（以现有项目记录为准）

下表复述随案例快照保存的验收矩阵中的状态；日期和证据命令见
[`docs/reference/prd-acceptance-matrix.md`](docs/reference/prd-acceptance-matrix.md)。这些状态不是本次整理
重新跑出的结果。

| 范围 | 记录状态 | 事实边界 |
| --- | --- | --- |
| `construction-v0`、碰撞/成功/超时、奖励和 Seed 复现 | `passed`（矩阵记录） | 以 simulation 源码和 simulation tests 为证据；不外推到真实道路。 |
| Python authority、WebSocket 会话、播放/暂停/单步 | `passed` 或 `partial`（按矩阵条目） | 浏览器边界和性能证据仍按矩阵中的 partial 项处理。 |
| 配置编辑与字段级浏览器错误提示 | `partial` | 后端 schema/解析存在，部分 UI 级证据仍待补。 |
| 策略比较、配对评估、Episode 保存/回放 | `partial`/`passed`（按矩阵条目） | 学习策略质量结论不在本材料中宣称。 |
| 可训练强化学习基线 | `partial`、延期 | 保留训练脚手架和 ONNX 推理合同；不声称重新训练、调参或质量达标。 |
| 完整开源交付文档、录屏演示 | 暂缓 | 本材料包是资料索引，不替代延期的完整交付物。 |

## 明确不宣称的内容

- `construction-v0` 是基于 HighwayEnv 的适配器，不是独立动力学引擎。
- ONNX 文件存在不等于学习策略质量已经验证；训练配置中的 `total_timesteps=256`
  只是一份实际合同配置，不能解读为生产训练结论。
- 单 Episode 比较表不是碰撞率/成功率统计；比例和置信区间只来自多 Seed 评估入口。
- 当前工作树有未提交改动，不能把本材料标为已发布版本或完整生产构建。

## 打包边界

材料采用 source-only 方式：保留源码、配置、schema、锁文件、测试、文档和可审计的模型
合同；排除 `.zf-*`、工作流状态、运行日志、临时 artifacts、诊断、浏览器录像、录屏和
构建缓存和项目规划投影。案例根目录 `LICENSE` 与 `THIRD_PARTY_NOTICES.md` 是许可证事实源。

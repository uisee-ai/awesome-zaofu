# Configuration and Schemas

## 稳定配置合同

主 schema 是 [`schemas/construction-config/v1.schema.json`](../../schemas/construction-config/v1.schema.json)，
其固定标识为 `construction-config/v1`，场景 ID 为 `construction-v0`。可直接从 schema
核验的边界包括：车道数 2–5、背景车辆数 0–50、交通密度大于 0 且不超过 3、激进车辆
比例 0–1、Seed 0–4294967295；施工车道和位置还受解析器的组合语义约束。

解析器 [`src/highwaypilot_lab/config/parser.py`](../../src/highwaypilot_lab/config/parser.py)
会展开默认值，并拒绝重复 JSON key、非有限数字、未知字段和不满足施工/车道语义的配置。

## 实际预设

以下是当前仓库中的真实文件，不在材料包中复制第二份容易漂移的内容：

- [`normal-v1.json`](../../configs/presets/normal-v1.json)
- [`aggressive-v1.json`](../../configs/presets/aggressive-v1.json)
- [`congested-v1.json`](../../configs/presets/congested-v1.json)
- [`dangerous-cut-in-v1.json`](../../configs/presets/dangerous-cut-in-v1.json)

训练配置 [`configs/training/dqn-v1.json`](../../configs/training/dqn-v1.json) 描述
Stable-Baselines3 DQN、训练 Seed、256 timesteps、ONNX opset 17 和资源限制；它是训练合同，
不是模型质量报告。

## 相关版本化 schema

- WebSocket：[`schemas/websocket/v1.schema.json`](../../schemas/websocket/v1.schema.json)
- Replay：[`schemas/highwaypilot-replay/v1.schema.json`](../../schemas/highwaypilot-replay/v1.schema.json)
- 策略评估：[`schemas/strategy-evaluation/v1.schema.json`](../../schemas/strategy-evaluation/v1.schema.json)

# User Guide

## 场景与会话

1. 在场景配置面板选择预设，或填写并校验 `construction-config/v1` 配置。
2. 启动会话后，服务端创建隔离的 Python 会话并发送 `highwaypilot-ws/v1` 快照。
3. 使用 Follow、Top、Free 相机查看 Three.js 场景；渲染层不改变仿真状态。

## 控制与评估

- 控制策略入口包括 `manual`、`random`、`qualified_rule` 和
  `construction_dqn_onnx`。
- 播放、暂停、单步、重置和倍率命令通过会话协议发送到服务端。
- 单次比较使用 `strategies/comparison.py`；多 Seed 配对统计使用
  `strategies/evaluation.py`。
- Episode 可由 Library 保存并通过 replay 接口回放。

## 边界

页面用于本地研究、评测和演示；不要将服务暴露到公网，也不要用于真实车辆控制。

# Architecture

```text
配置/schema
    │
    ▼
Python RuntimeService ── Session ── WebSocket v1 ── TypeScript HMI
    │                         │                         │
    │                         └─ Episode recorder      └─ Three.js render/interpolation
    │
    ├─ ConstructionSimulation (HighwayEnv adapter)
    ├─ Gymnasium construction-v0
    ├─ strategies: manual / random / qualified_rule / construction_dqn_onnx
    └─ comparison + paired evaluation + Episode Library/replay
```

## 权威边界

`src/highwaypilot_lab/simulation/authority.py` 是仿真事实状态入口。车辆动力学、碰撞、
奖励、终止状态、TTC 和 Seed 派生均在 Python 侧完成。前端场景只消费服务快照，不重复
实现车辆动力学；`HighwayScene.ts` 负责道路、施工区、车辆、轨迹和相机的显示。

## 确定性与策略

`rng/contract.py` 为配置计算 digest 并命名 RNG stream；`simulation` 和 strategy tests
覆盖相同配置/Seed 的重置和轨迹契约。ONNX runtime 读取模型 manifest 的输入/输出和 hash
合同，策略在 `policy.py` 中以 `argmax` 选择 Q 值动作。训练质量仍属于延期范围。

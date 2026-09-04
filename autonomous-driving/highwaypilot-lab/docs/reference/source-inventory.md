# Source Inventory

以下清单只列出当前工作树中可定位的事实源；源码不在材料包中复制第二份。

## 服务与仿真

- `src/highwaypilot_lab/api/server.py`：FastAPI、HTTP 和 WebSocket 服务边界。
- `src/highwaypilot_lab/simulation/authority.py`：仿真 authority。
- `src/highwaypilot_lab/simulation/environment.py`：HighwayEnv 适配、施工、交通和奖励。
- `src/highwaypilot_lab/simulation/gym_env.py`：Gymnasium `construction-v0`。
- `src/highwaypilot_lab/rng/contract.py`：Seed/RNG/digest 合同。

## 配置与协议

- `schemas/construction-config/v1.schema.json`
- `schemas/websocket/v1.schema.json`
- `schemas/highwaypilot-replay/v1.schema.json`
- `schemas/strategy-evaluation/v1.schema.json`
- `src/highwaypilot_lab/config/parser.py`
- `src/highwaypilot_lab/protocol/messages.py`
- `src/highwaypilot_lab/session/core.py`

## 策略、模型和回放

- `src/highwaypilot_lab/strategies/policy.py`
- `src/highwaypilot_lab/strategies/comparison.py`
- `src/highwaypilot_lab/strategies/evaluation.py`
- `src/highwaypilot_lab/model/runtime.py`
- `models/construction-dqn-v1/manifest.json`
- `models/construction-dqn-v1/model.onnx`
- `training/train_dqn.py`
- `training/build_model_evidence.py`
- `src/highwaypilot_lab/episodes/library.py`
- `src/highwaypilot_lab/episodes/replay.py`

## Web HMI

- `web/src/hmi/App.ts`
- `web/src/hmi/ApiClient.ts`
- `web/src/hmi/HmiState.ts`
- `web/src/hmi/renderer/HighwayScene.ts`
- `web/src/hmi/renderer/VehicleGeometry.ts`
- `web/src/hmi/renderer/VehicleAssetCatalog.ts`
- `web/src/hmi/renderer/TrafficVehicleFleet.ts`

## 预设与测试入口

- `configs/presets/normal-v1.json`
- `configs/presets/aggressive-v1.json`
- `configs/presets/congested-v1.json`
- `configs/presets/dangerous-cut-in-v1.json`
- `configs/training/dqn-v1.json`
- `tests/simulation/test_gym_registration.py`
- `tests/simulation/test_rng_contract.py`
- `tests/api/test_strategy_comparison.py`
- `tests/strategies/test_evaluation.py`
- `tests/training/test_model_contract.py`
- `tests/web/hmi/highwayScene.test.ts`
- `tests/web/hmi/appShell.test.ts`

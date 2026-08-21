# 架构说明

## 数据流

```text
自然语言 / JSON / 模板
        ↓
ScenarioSpec 规范化与 Schema 校验
        ↓
后端能力预检 + 不可变 revision + Owner 确认
        ↓
InputSnapshot / RunManifest
        ↓
single-run Worker（MetaDrive 或 SMARTS）
        ↓
OutputStaging → Supervisor 原子发布
        ↓
RunResult / ArtifactIndex / trajectory / metrics
        ↓
Web 证据面板与 Three.js 3D 回放
```

## 主要模块

- `authoring/`：ScenarioSpec、模板、草稿、revision、导入导出和 Provider。
- `core/`：严格 JSON、领域模型、编译器和环境合同。
- `runtime/`：适配器、Worker、快照、确认与终态管理。
- `orchestration/`：实验状态、控制命令、持久化和恢复。
- `repro/`：三次复现、容差比较、策略回归和反事实。
- `replay/`：轨迹合同、插值、道路投影、参与者表现和相机。
- `security/`：路径、环境、资源、秘密脱敏和产物边界。
- `web/`：loopback API、协调器、目录和静态单页界面。

## 后端边界

Web API 和 ScenarioSpec 不暴露 MetaDrive/SMARTS 内部对象。Adapter 负责把稳定领域合同
映射到具体后端；只有 `exact` 能力实例可直接执行，`lossy` 或 `unsupported` 必须进入
诊断/确认或阻止运行。跨后端结果只能按声明的共同指标比较，不能宣称动力学等价。

## 证据边界

Worker 读取只读 InputSnapshot，只写自己的 OutputStaging。Supervisor 负责超时、进程树
终止、终态转换和原子发布。回放消费已发布轨迹，不能改变仿真结果。

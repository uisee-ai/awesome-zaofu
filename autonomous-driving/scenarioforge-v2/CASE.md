# ScenarioForge v2 Case

## 案例定位

ScenarioForge v2 展示 ZaoFu 如何把“跨仿真后端的场景创作与可追溯执行”从需求讨论
推进到可运行产品。与仓库中原 ScenarioForge 案例相比，本案例保留独立目录，聚焦统一
创作入口、MetaDrive + SMARTS 双后端、严格运行授权和更完整的 3D 场景表达。

## ZaoFu 交付路径

1. 通过 Channel 多视角讨论冻结 ScenarioSpec、后端边界、复现语义和安全约束。
2. 将 P0 拆为 MetaDrive 最小闭环、Web 创作、场景库、回放与回归切片。
3. 在 P1 接入 SMARTS、多智能体场景、自然语言离线意图和跟车回放。
4. 通过合同测试、真实仿真、浏览器旅程和候选 Gate 持续发现并修复跨切片问题。
5. 将最终源码以 source-only 快照发布，排除 ZaoFu 状态、运行日志和大型媒体证据。

## 当前可运行范围

- MetaDrive 五类模板及严格 JSON 单次执行。
- SMARTS 五类本地合成场景及多参与者轨迹。
- 自然语言受支持意图到待确认 ScenarioSpec 草稿。
- revision、preflight、确认、single-run Worker 和不可变结果。
- 3D 路面、参与者、信号灯、事件、指标和跟车视角。
- CLI 编译、运行、复现与本地实验控制。

自然语言入口是离线规则型参考 Provider，只识别已声明 benchmark intent；它不是任意文本
生成器，也不调用云端模型。双后端共享领域合同，不承诺动力学或指标完全等价。

## 发布快照边界

此目录取自源项目 commit `6d90539735602f7cfda865fa85a48099ea689fb1`，采用 source-only
打包。发布保留源码、锁文件、场景资产、示例和测试；排除 `.zf-*`、workflow 投影、
diagnostics、历史 intake、运行产物、截图、视频和 Playwright trace。
依赖这些历史 Gate 文档本体的追溯测试也随 evidence 一并排除；产品合同、运行、安全和
浏览器测试仍保留。

## 风险与限制

- 页面和仿真仅面向本地研究，不可直接控制真实车辆。
- MetaDrive 与 SMARTS 的动作、车辆动力学和指标不能视为等价。
- 场景与程序化车模是合成表达，不代表传感器级或影视级真实感。
- 默认依赖组较大，首次安装与首次仿真可能较慢。
- 当前不是多用户、远程调度或生产级任务服务。

## 发布验证

- `uv lock --check` 通过。
- 创作、合同、回放与安全分层测试：157 passed。
- 全新 Web 服务由 Chromium 打开成功，10 个双后端模板可加载，统一运行按钮可用。
- 完整真实后端矩阵在本次发布主机上因并存仿真进程造成资源竞争，未宣称全量通过；其中
  已观测到 86 passed，随后 MetaDrive calibration 单例超过 120 秒。该限制不以扩大超时
  或复制历史 evidence 掩盖。

## 许可证结论

发布前对源码、锁文件、场景资产和 vendored 文件进行了边界审计。原创内容按 Apache-2.0
发布；Three.js MIT 文件保留原许可证；SUMO 生成路网按 EPL-2.0 标注；外部 MetaDrive、
SMARTS 与 SUMO 由包管理器安装，不作为本目录源码重新分发。详见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

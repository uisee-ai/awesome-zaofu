# ScenarioForge Showcase 最小产品闭环

> 状态: active

## 背景

ScenarioForge 当前已经具备严格 `ScenarioSpec`、真实 MetaDrive 0.4.3 执行、异步作业、
资源隔离、不可变 Run Bundle、离线 Three.js 回放和 Bundle 对比能力。但当前产品仍主要
证明“同一单车运行可以复现”，尚不能清晰证明 ScenarioForge 的核心价值：把危险驾驶
假设转换成可执行、可解释、可比较并可沉淀为回归资产的实验。

当前代码事实必须作为本 Issue 的起点：

- `src/scenarioforge/compiler/compiler.py` 将多数 actor behavior、goal、event trigger、
  static obstacle 和 safety 字段保存到 `p0_provenance`。
- `src/scenarioforge/runtime/worker.py` 只消费 `metadrive_config`，当前以固定 ego action
  推进仿真，未执行声明的 actor/event 语义。
- 当前 trace 主要记录 ego，Web 结构化编辑主要覆盖 lane count、traffic density 和 seed。
- `docs/manual/user-guide.md` 的六次同 Seed 运行证明重复性，但不是策略或安全结果 A/B。

## 目标

交付一个可以从 Web 和 CLI 真实演示的“前车急刹”闭环：用户定义 ego 与 lead car，lead
car 在确定触发条件下急刹；ScenarioForge 用锁定 MetaDrive 后端真实执行多个参数/Seed，
记录所有参与者轨迹和事件，计算最小 TTC 与安全 verdict，回放失败点，并比较 baseline
与 candidate Bundle。失败案例能够作为仓库内回归场景再次执行。

本 Issue 是现有 ScenarioForge 的产品补全，不重新设计通用仿真平台，也不把未执行语义
伪装成已支持能力。

## 范围

### 1. 可执行场景语义

- 扩展或收敛 `ScenarioSpec v1` 的受限字段，使 `following-emergency-brake` 能明确表达：
  ego/lead 初始车道、纵向位置和速度，事件目标 actor、触发时间或距离，以及目标速度或
  制动动作。
- compiler 必须把每个被接受的执行语义映射到真实 runtime plan；只写入 provenance 不算
  execution mapping。不能执行的 behavior/event/goal 必须在运行前返回字段级 unsupported
  错误，禁止静默降级。
- MetaDrive runtime 必须创建并绑定指定 lead actor；不得用随机同密度交通代替该 actor。
- ego 与 lead 的控制策略必须是仓库内版本化、确定性的受限内建策略，不接受任意用户
  Python、插件、URL 或宿主路径。

### 2. 多参与者证据与安全判定

- 每个 canonical tick 记录所有声明 actor 的稳定 id、位置、速度、航向和关键状态。
- 记录事件触发 tick、目标 actor、动作与执行结果。
- 至少计算 collision、off-road、route progress、minimum TTC、minimum headway 和
  event-to-response latency；指标公式、单位和缺失值语义必须版本化。
- `safety` 约束必须参与场景 verdict，不能只作为展示字段。Bundle 中保存约束、指标和
  verdict 的可追溯关系。

### 3. 真实回放与对比故事

- Three.js 回放必须同时显示 ego、lead、急刹事件标记、最危险 tick 和当前 TTC。
- baseline/candidate 必须是两个独立不可变 Bundle；比较结果明确列出安全 verdict、最小
  TTC、碰撞和关键事件差异。重复执行同一配置只能称为 reproducibility，不得标为 A/B。
- 提交一个确定可复现的安全 baseline 与一个确定触发安全退化的 candidate fixture，二者
  都必须来自真实 MetaDrive，不得使用 synthetic success 或手工篡改结果。
- 失败 candidate 能作为 committed regression case 再执行并获得相同离散终态；数值字段
  使用校准 tolerance。

### 4. 最小 Web 产品路径

- 保留 JSON/YAML 编辑，同时为本场景提供 actor 初始状态、急刹事件和 safety threshold
  的结构化控件。
- 增加只读场景预览，运行前能看见道路、ego、lead 和事件位置/时间；不要求 CAD 或自由
  拖放编辑器。
- 页面从样例开始可以完成：加载 -> 编辑 -> 校验 -> 真实 run -> 状态 -> 指标 -> 多 actor
  回放 -> Bundle 对比 -> 回归案例引用。
- 错误必须在 UI 中显示字段位置；安全边界继续保持 capability token、CSRF、loopback 和
  offline/fail-closed 约束。

### 5. 文档与交付证据

- 重写用户指南开头，先解释“危险场景假设如何变成回归资产”，部署、token 和 tmux 移到
  安装/运维附录。
- 使用真实页面截图和真实 Bundle 数据说明 baseline、failure、最危险 tick 和 A/B 结果。
- 生成逐项验收矩阵，绑定目标 commit、ScenarioSpec/compiled/runtime digests、真实
  MetaDrive provider/asset 版本、测试、浏览器证据和 Bundle manifest。

## 明确非目标

- SMARTS Adapter、跨后端执行或跨后端结果等价。
- 自然语言生成场景。
- 通用参数优化器、大规模失败搜索或失败案例自动最小化。
- 任意用户策略、任意 Python、插件、外部 URL 或数据集导入。
- CAD 级道路编辑、分布式运行、多用户、HIL 或自动驾驶安全认证。
- 一次性补齐现有五个样例的全部 behavior；未实现语义应明确拒绝并列入后续 Issue。

## 验收标准

1. `following-emergency-brake` 的 ego、lead 和急刹事件均进入真实 MetaDrive runtime，且
   actor identity 与触发结果可从 trace 回读。
   -> verify: compiler/runtime focused tests + 真实 MetaDrive Bundle；检查 runtime plan、
   actor ids、event receipt 与 trace，不接受仅有 provenance 的证据。
2. 每个被 schema 接受的执行字段都具有 runtime consumer；不支持字段在执行前 fail
   closed，并返回稳定字段路径和错误码。
   -> verify: field-to-consumer coverage matrix + unsupported negative fixtures，覆盖率 100%。
3. 真实 Bundle 包含所有声明 actor 的逐 tick 轨迹以及版本化 TTC/headway/event metrics；
   safety 约束能够改变场景 verdict。
   -> verify: deterministic metric unit tests + 锁定 MetaDrive provider real run assertions。
4. 安全 baseline 和退化 candidate 生成两个不同、不可变、完整可校验的 Bundle；对比结果
   能定位最危险 tick，并将差异归因到实际场景结果而非 wall/CPU/RSS 抖动。
   -> verify: exact replay、tolerance compare、tamper negative 和真实 A/B report。
5. Web 黄金路径可展示运行前双车场景、真实作业状态、双车回放、事件、最小 TTC、安全
   verdict 和 baseline/candidate 差异，无 mock API 或 synthetic provider。
   -> verify: production build + Docker Playwright 网络记录、截图与 bundle digest。
6. committed regression case 可从 CLI 与 Web 重跑；相同 provider/config/seed 的离散终态
   一致，数值差异满足校准 profile。
   -> verify: clean temporary output root 下执行两次 real-provider regression E2E。
7. 现有 schema、安全、job lifecycle、Bundle integrity、offline replay 和 CLI 契约不回归。
   -> verify: 受影响 backend/API/CLI/Web 测试、ruff、Web build 和 release focused gate。
8. 用户指南首屏说明 ScenarioForge 的问题、输入、输出和真实失败故事，运维内容不再占据
   产品叙事入口。
   -> verify: 文档引用真实证据，不宣称 SMARTS、自动搜索或未实现 behavior 已完成。

## 工作流约束

- 使用 ZaoFu `IssueFlow` 的 `issue-flow-v4-task-pipeline`，显式
  `taskPipeline.mode: blocking`；这是本项目授权的 canary，不改变 ZaoFu 全局默认。
- Task 必须按垂直交付拆分，优先顺序为：runtime semantics -> evidence/metrics -> Web story ->
  real E2E/docs。每个 Task 独立执行 Impl -> Task Verify -> Integration Admission。
- Candidate 使用增量串行 CAS 集成，partial Candidate 禁止自动交付，最终验证目标必须是
  frozen exact commit。
- 每个实现 Task 先写失败测试；真实 MetaDrive 与 Docker Playwright 是最终显式测试层，
  mock 测试不能替代。
- 规划产物中的 AC-EVID-003 必须与其他真实 Bundle 验收项共同绑定到同一条
  `real-following-brake-e2e` 命令。该命令必须产出两个真实、不同且不可变的 baseline 与
  candidate Bundle，并断言最危险 tick、safety verdict、minimum TTC、collision 和关键
  事件差异；acceptance matrix、test matrix、Task validation 与 real E2E matrix 的
  acceptance ids 必须一致。仅绑定 focused pytest 不满足该 AC。
- 现有未提交证据目录和历史 `.zf-*` state 不得进入 Candidate。

## 完成定义

只有在真实 MetaDrive baseline/failure 两条路径、全 actor trace、TTC/safety verdict、Web
回放/比较、回归重跑和逐项证据矩阵全部通过后，本 Issue 才能完成。单纯增加 schema、
provenance、按钮、截图或 mock fixture 不构成完成。

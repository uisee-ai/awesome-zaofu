# ScenarioForge MetaDrive P0 产品闭环

> 状态: active

## 背景

现有候选提交 `0208b03` 已通过 ScenarioSpec、compiler、隔离 runner、不可变
Run Bundle、Three.js 精确回放、安全负面测试和 release gate 等底层验证；但这些
能力尚未形成一个可从源码直接使用、可用示例数据验证、并能完整覆盖原始 P0 PRD
用户路径的产品。旧运行证据只能作为基线，不能替代本 Issue 对目标提交的重新验收。

权威需求来源：

- 原始 P0 PRD 的仓库内不可变快照：
  `docs/prd/scenarioforge-metadrive-p0-r1.json`
- MetaDrive：<https://github.com/metadriverse/metadrive>
- MetaDrive 场景格式参考：<https://github.com/metadriverse/metadrive-scenario>
- SMARTS：<https://github.com/huawei-noah/SMARTS>，仅作后续适配边界参考，本轮不接入。

## 已确认差距

1. `ScenarioSpec` 仅表达道路块序列、车道数/宽度、actor id/role 和交通密度，
   不能表达 P0 产品所需的初始状态、目标、受限行为、静态障碍、事件触发及安全约束。
2. 仓库没有第一方可发现、可加载、可直接运行的样例场景库；Web 也没有样例入口。
3. `POST /api/runs` 虽返回 `202`，实际同步阻塞至运行结束；没有 job 状态查询、取消和
   明确的终态接口。
4. oracle 已有 `resimulate` / `compare_bundles`，但 Web、API 和 CLI 均无法使用，
   因而 AC-09 只是内部库能力，不是产品能力。
5. `scenarioforge` 命令仅启动 Web 服务，缺少 validate、compile、run、status、cancel、
   replay verify、resimulate/compare 等可脚本化操作。
6. Web 主要是 JSON 文本编辑和回放面板，缺少结构化场景编辑、场景预览、样例选择、
   多 seed 请求、运行状态/取消以及重新仿真结果展示。
7. 交付 dossier 的最新 claimset 仅覆盖后续 R14 gap claims，没有在目标提交上重新绑定
   PRD AC-01..AC-14、源码、测试、真实 provider 和浏览器证据。

## 本轮范围

### 1. 场景模型、编译与样例

- 以向后兼容方式扩展 `ScenarioSpec v1` 的受限 P0 领域字段：actor 初始状态和目标、
  枚举化行为、静态障碍、事件触发及安全约束。不得接受任意代码、URL、宿主路径或插件。
- compiler 对每个新增字段必须有确定映射，或在编译前返回字段级“不支持”错误；禁止
  静默丢字段。
- 提交至少 5 个 MetaDrive-only 样例，覆盖直道跟车、汇入、换道冲突、十字路口和
  静态障碍避让。样例必须通过 schema、canonical round trip 和 deterministic compile。
- 提供样例 catalog API，并在 Web 中可选择、加载和编辑。

### 2. 运行生命周期与 oracle

- 将运行改为真正的有界异步 job：创建、查询状态、取消、终态 Bundle 引用；状态至少
  包含 queued/running/completed/partial/cancelled/aborted/failed。
- 保留既有进程隔离、资源上限、零静默重试和原子封存语义；取消必须终止进程树并产生
  可审计终态，不得只更新内存状态。
- 对外提供独立的 exact replay verify 和 re-simulation/compare 操作。重新仿真必须创建
  新 Bundle，并返回 pass/regression/incompatible；不得覆盖 baseline。
- 为上述能力提供用户 CLI，CLI 与 API 调用同一 domain service，不复制业务规则。

### 3. Web 产品路径

- 保留源码 JSON/YAML 编辑，同时提供结构化字段编辑和只读 2D 场景预览；固定格式控件
  必须响应式且不遮挡。
- 支持样例选择、校验、canonical preview、JSON/YAML 导出、多 seed run、状态刷新、
  cancel、指标、Three.js exact replay 和 re-simulation 结果。
- 所有操作连接当前 ScenarioForge API；不得使用 mock 或旧项目后端冒充成功。
- 保持 loopback、Origin、capability token 和 CSRF 边界；错误必须在 UI 可见且可定位。

### 4. 交付、文档与证据

- 更新 README 和本地安装/操作文档，给出 CLI 与 Web 的最短可复现路径。
- 在当前目标提交上生成 AC-01..AC-14 对照表，每条包含实现引用、测试引用、证据 owner
  和通过/阻塞状态。不能引用旧 commit 的通过结果作为当前提交唯一证据。
- 对比 MetaDrive/MetaDrive Scenario 的场景表达和运行方式，明确已采用能力与未采用边界；
  SMARTS 仍为 P1，不得增加假适配器或通用 backend 抽象。

## 明确非目标

- SMARTS、跨后端执行或结果比较。
- 自然语言场景生成、搜索/优化、失败用例最小化。
- 云端、分布式、多用户、任意 Python/插件/用户策略。
- CAD 级自由道路创作、外部数据集分发、HIL 或安全认证。
- 跨平台 bitwise trajectory、video 或 pixel 一致性。

## 验收标准

1. 五个提交样例逐个 load/export/reload/compile，两次编译 digest 一致。
   -> verify: 自动化 sample matrix 测试通过，且报告列出 5 个样例和 digest。
2. 每个新增 ScenarioSpec 字段均有 compiler mapping 或明确拒绝。
   -> verify: field-mapping coverage 为 100%，负面 fixture 不发生静默降级。
3. 创建 run 后 API 立即返回 job id；可查询状态并在运行中取消。
   -> verify: lifecycle 测试证明进程树退出、Bundle 封存、无静默重试。
4. baseline 可 exact verify，并可触发新 Bundle 的 re-simulation。
   -> verify: pass、regression、incompatible 三类 oracle 测试及不可覆盖断言通过。
5. CLI 可完成 samples/list、validate、compile、run/status/cancel、replay verify 和 compare。
   -> verify: 隔离临时目录中的 CLI E2E 全绿，退出码和错误输出稳定。
6. Web 可从样例开始完成编辑、校验、导出、真实 run、状态/取消、指标、回放和重新仿真。
   -> verify: production build Playwright E2E 通过；关键路径网络记录无 mock endpoint。
7. 至少一个样例在锁定 MetaDrive 0.4.3 + 官方校验资产上真实运行并生成可加载 Bundle。
   -> verify: 记录 provider/version/asset digest、命令、Bundle digest 和 replay 检查结果。
8. 当前提交重新通过 Python focused/full suite、ruff、Web build、浏览器 E2E、release gate。
   -> verify: 命令、退出码和日志/报告引用写入交付 dossier。
9. AC-01..AC-14 在当前目标提交均有逐项状态和证据；任何环境阻塞必须标为 blocked，
   不得把历史证据或 mock 当作通过。
   -> verify: completion gate 校验 claimset、target commit 和 evidence digest 后通过。

## 交付约束

- 按独立 vertical slice 分工，避免多个 lane 同时持有同一根级文件；根级 manifest 和最终
  assembly 由一个明确 owner 处理。
- 实现采用 TDD：先复现缺口，再实现，再运行受影响调用方和共享契约测试。
- 所有真实 provider 资产安装在工作目录或临时目录，不提交第三方资产、缓存或 secret。
- 最终交付必须是可审查 commit，不修改原候选分支，不直接在原演示目录上开发。

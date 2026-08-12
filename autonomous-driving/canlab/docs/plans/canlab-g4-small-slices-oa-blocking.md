# CAN Lab G4 Small-Slice OA Blocking Run

## Goal

基于 canonical PRD 实现 CAN Lab P0 MVP。保持 PRD 的 AC-01 至 AC-17、D-06、
D-08 和 synthetic/offline/passive-only 边界不变。本 Run 用于验证较小任务切片和
Orchestrator Agent `plan_candidate` blocking checkpoint，不新增产品需求。

## Planning Boundary

- 生成 6 至 7 个 implementation work units。
- 每个 work unit 交付一个可观察结果，目标 2 至 5 个 AC，硬上限 8 个。
- 每个 work unit 目标 4 至 10 个具体文件或路径，硬上限 12 个 scope entries。
- 每个 work unit 只有一个 owner、一个主要验证命令和明确依赖。
- 不允许单个 Foundation task 同时拥有 package/config、assets、fixture 和 boundary scanner。
- Candidate Verify 是独立只读验证阶段，不得成为 implementation writer task。
- 原始产品 AC 始终只有 17 个。实现约束、环境资格、command registry 和 Critic 修复项
  放入 Task Map、Test Matrix、Risk Register 或独立 backlog，不得新增为产品 AC。
- 最新稳定 Chromium 作为项目级受控验证输入和 E2E evidence；本产品 Plan 不得为了它
  发明新的通用 Runtime producer、receipt 子系统或第 18 个产品 AC。
- Plan 被拒后在本 Task、本 Run 内进行 bounded replan，不创建 G5 Task。

## Suggested Slices

Planner 可以根据依赖调整，但必须解释偏差：

1. 最小项目骨架与唯一 command registry。
2. Synthetic DBC、fixture generator 与 asset contract。
3. DBC decode 与 trace domain。
4. Replay、Step、seek、loop 与 callback isolation。
5. HealthMetrics 与 DashboardProjection。
6. Browser explorer、controls、trace 和 dashboard integration。
7. App assembly；最终 lint/test/build/Chromium E2E 由 Candidate Verify 独立执行。

## Acceptance

- Canonical PRD AC-01 至 AC-17 全部映射到 Task Map 和 Test Matrix，不能遗漏或扩写。
- OA blocking 必须在 Plan candidate 进入 Impl 前给出 `adopt`、`revise`、`clarify` 或
  `block` 的类型化决定。
- `revise` 必须返回小型结构化 delta，并保留在同一 Run 的 replan feedback 中。
- Impl 只在机械 Plan admission、Critic 和 OA blocking 均通过后启动。
- 最终执行 `npm run lint`、`npm test`、`npm run build` 和
  `npm run test:e2e -- --project=chromium`。

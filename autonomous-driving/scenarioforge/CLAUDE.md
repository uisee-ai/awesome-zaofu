# CLAUDE.md

本项目使用 ZaoFu 管理 multi-agent 开发流程。

## Claude Code Rules

- 开始工作前先阅读 `AGENTS.md`。
- 项目名: `scenarioforge-case2-full-20260802t133411z`。
- `zf.yaml` 是唯一 ZaoFu 控制面配置。
- `project.state_dir` 当前解析为 `.zf-scenarioforge-case2-full-20260802t133411z`;不要把运行态文件当作源码维护。
- 不要直接写 `events.jsonl`、`kanban.json`、`session.yaml`、`feature_list.json`、`role_sessions.yaml`。
- 状态变更通过 `zf` CLI、受控事件写入或 kernel helper 完成。
- 普通交互式开发会话没有 `Active task: <task_id>` briefing 时,不要自行 emit
  task/workflow event 或 heartbeat。
- 修改代码时保持范围收敛,优先沿用项目现有模式。
- 交付前运行项目约定的测试;无法运行时说明阻塞项。

<!-- ZF:NOTES:START -->
## 项目说明 (operator notes)

IssueFlow 在基于 product dev 的独立 worktree 中补齐 ScenarioForge MetaDrive P0；不得修改原 candidate/main 工作树。
<!-- ZF:NOTES:END -->

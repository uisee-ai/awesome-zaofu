# CLI 与自动化

所有命令都可在模块形式和安装后的脚本形式之间二选一：

```bash
uv run scenarioforge --help
uv run python -m scenarioforge --help
```

全局参数必须放在子命令之前：

```bash
uv run scenarioforge --project-root "$PWD" --workspace "$PWD/.scenarioforge-runs" health
```

## 场景命令

```bash
uv run scenarioforge validate --json examples/p0c/brake_lead.json
uv run scenarioforge preflight --json examples/p0c/brake_lead.json
uv run scenarioforge compile examples/p0a/brake_lead.json
uv run scenarioforge run examples/p0a/brake_lead.json \
  --run-id run-001 --attempt-id attempt-001 --timeout-seconds 120
uv run scenarioforge reproduce examples/p0a/brake_lead.json \
  --comparison-id compare-001 --run-id-prefix repeat --timeout-seconds 120
```

标准输出为稳定 JSON；合同错误输出到标准错误并返回非零状态码，便于 CI 使用。

## 实验命令

```bash
uv run scenarioforge experiment-submit --json experiment.json \
  --idempotency-key submit-001
uv run scenarioforge experiment-query
uv run scenarioforge experiment-query --experiment-id EXPERIMENT_ID
uv run scenarioforge experiment-control EXPERIMENT_ID start --command-id start-001
uv run scenarioforge experiment-control EXPERIMENT_ID pause --command-id pause-001
uv run scenarioforge experiment-control EXPERIMENT_ID resume --command-id resume-001
uv run scenarioforge experiment-control EXPERIMENT_ID stop --command-id stop-001
uv run scenarioforge experiment-recover
```

可用控制操作为 `start`、`pause`、`step`、`resume`、`stop` 和 `reset`。命令 ID 用于避免
同一控制请求被重复应用。

## 诊断命令

```bash
uv run scenarioforge health
uv run scenarioforge comparison-contract
uv run scenarioforge trace
uv run scenarioforge candidate-contract --candidate-commit COMMIT_SHA
```

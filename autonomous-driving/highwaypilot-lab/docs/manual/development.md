# Development and Verification

源码位于案例根目录 `src/highwaypilot_lab/`，Web 源码位于 `web/src/`，测试位于 `tests/`。
建议按以下层次复核：

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/config tests/simulation -q
PYTHONPATH=src .venv/bin/python -m pytest tests/session tests/strategies tests/api tests/library -q
npm test
npm run typecheck
npm run build
npm run test:e2e
```

本案例生成时没有把这些命令的新输出写成发布通过结论；历史验收状态见
[`../reference/prd-acceptance-matrix.md`](../reference/prd-acceptance-matrix.md)。

# 公开发布清单

这是将 Sensor Workbench 收录到 `awesome-zaofu` 前的人工检查清单。

## 保留

- `app/src/`、`app/tests/`、`app/scripts/` 和 `app/index.html`
- `app/package.json`、`app/package-lock.json`、`app/tsconfig.json`、`app/vite.config.ts`
- `docs/product/`、`docs/manual/`、`app/docs/` 中的产品和操作文档
- 合成 fixture、黄金 fixture 及其摘要 sidecar
- `AGENTS.md`、`CLAUDE.md`、`zf.yaml`、`skills/` 以及根目录占位目录；这些文件与现有
  `awesome-zaofu` 案例的公开快照保持一致
- 小型、脱敏且被测试引用的 `app/artifacts/tasks/` 和 `app/artifacts/spikes/`
- `README.md`、`CASE.md`、`case.yaml`、`LICENSE`

## 排除

- `.zf-sensorworkbench-new/`、`.codex/`、`events.jsonl`、workflow projection 和本机日志
- `node_modules/`、`dist/`、`test-results/`、Playwright report/trace 和临时 artifacts
- `app/artifacts/e2e/`、`artifacts/intake/`、`artifacts/workflow/` 和 `artifacts/showcase/`
- 演示视频、PPT、WPS、录屏帧和音频源文件
- 任意真实 nuScenes、OpenLane、Waymo 数据、模型权重、压缩包或绝对路径清单
- `issue_record.md` 以及含访问令牌、个人路径或内部会话信息的日志

## 发布前命令

在干净临时目录中执行：

```bash
npm ci --prefix app
npm run typecheck
npm run build
npm --prefix app run test:unit
CHOKIDAR_USEPOLLING=1 npm --prefix app run e2e:synthetic
npm run verify:license
```

然后确认 `git status --short` 为空，并将 `case.yaml` 的
`source.commit` 替换为最终发布 commit。真实数据模式只在使用者自己的机器上验证，
不得把数据目录复制进发布快照。

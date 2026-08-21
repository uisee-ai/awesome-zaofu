# 公开发布清单

## 保留

- `src/scenarioforge/` 产品源码和本地 Web 静态资源
- `assets/` 中的合成场景、SUMO 路网与资产 manifest
- `examples/`、`tests/`、`pyproject.toml`、`uv.lock`
- `README.md`、`CASE.md`、`case.yaml` 和 `docs/manual/`
- `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`
- Three.js vendor 文件及原始 MIT 许可证

## 排除

- `.zf-*`、`.codex/`、ZaoFu event/workflow/attempt 投影和本机状态
- `.scenarioforge-*`、运行日志、OutputStaging 和仿真产物
- `artifacts/`、`diagnostics/`、`docs/intake/`、历史 Gate/evidence 文件
- 只验证上述历史 Gate/evidence 文档存在性的追溯测试（产品行为测试保留）
- Playwright trace、视频、截图和浏览器报告
- `.venv/`、缓存、覆盖率、构建目录
- 访问令牌、邮箱、绝对个人路径、客户或真实车辆数据
- MetaDrive/SMARTS/SUMO 源码归档、真实地图、模型权重和第三方数据集

## 发布前命令

```bash
uv lock --check
uv run pytest -q
rg -n --hidden -S \
  'ghp_|github_pat_|sk-[A-Za-z0-9]|BEGIN .*PRIVATE KEY|/home/[^/]+/' \
  --glob '!.git/**' .
git status --short
```

人工复核 `THIRD_PARTY_NOTICES.md`、Three.js 原许可证、SUMO 路网来源以及 `case.yaml` 的
源 commit。若新增图片、3D 模型、地图、字体、数据或代码生成物，必须先补充来源、作者、
许可证和修改说明，不能仅依赖文件扩展名判断可发布性。

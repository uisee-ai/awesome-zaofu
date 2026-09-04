# Publication Checklist

## 保留

- `README.md`、`CASE.md`、`case.yaml`、`NOTICE`、`THIRD_PARTY_NOTICES.md`
- `docs/manual/`、`docs/release/` 和 `source-manifest.json`
- 对当前源码、配置、schema、模型合同和测试入口的路径索引

## 排除

- `.zf-*`、`.highwaypilot`、事件/工作流投影和本机运行态
- `artifacts/`、`diagnostics/`、`dist/`、测试缓存和覆盖率产物
- `planning/` 投影、事件账本、workflow/attempt 状态和其他项目控制面数据
- `training/assets/` 中的 checkpoint、回放和训练运行证据；对应的训练产物存在性测试
  不属于 source-only 快照
- Playwright trace、浏览器报告、截图、录屏、视频和临时模型输出
- 密钥、令牌、绝对个人路径、客户数据、真实车辆数据和第三方源码归档

## 发布前复核

```bash
uv lock --check
PYTHONPATH=src .venv/bin/python -m pytest -q
npm test
npm run typecheck
npm run build
git status --short
```

人工复核 `case.yaml` 的 source commit、`source-manifest.json` 的 hash、根目录许可证和
第三方声明。新增模型、图片、字体、地图或数据集时，必须补充来源、作者、许可证和修改
说明；本材料不因文件扩展名而默认其可再分发。

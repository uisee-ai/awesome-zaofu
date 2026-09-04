# Quick Start

本页是与官方案例 `docs/manual/quick-start.md` 对齐的入口；可执行命令以材料包根目录
[`README.md`](../../README.md) 和项目根目录脚本为准。

```bash
cd /path/to/highwaypilot-lab
uv sync --frozen --group dev
npm ci
PATH="$PWD/.venv/bin:$PATH" HIGHWAYPILOT_PORT=8000 ./scripts/start-demo.sh
```

启动后访问 `http://127.0.0.1:8000/`。启动脚本会在 Web 源码比发布装配更新时调用
`scripts/assemble-release.py`；使用 `Ctrl-C` 停止服务。

本案例不包含项目规划投影、`dist/` 和 `artifacts/` 等项目级装配输入。单独从
GitHub 下载后，应先按 `docs/release/publication-checklist.md` 准备这些外部输入；本页不
把缺少的生成物宣称为已通过的发布环境。

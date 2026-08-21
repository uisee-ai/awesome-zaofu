# 开发与验证

## 安装开发环境

```bash
uv sync --frozen
uv run playwright install chromium
```

## 基础检查

```bash
uv lock --check
uv run pytest -q
```

## 分层执行

资源有限或排查问题时，可以先跑纯合同测试：

```bash
uv run pytest -q \
  tests/authoring \
  tests/p1/contracts \
  tests/p1/replay \
  tests/test_strict_json.py \
  tests/test_security_boundaries.py
```

再跑真实后端相关用例：

```bash
uv run pytest -q tests/p0c/scenarios tests/p1/smarts
```

最后运行 Web/Playwright：

```bash
uv run pytest -q tests/web
```

浏览器用例会启动本机服务并创建临时运行产物。不要把测试生成的 trace、视频或运行目录
提交到公开仓库。

## 修改依赖

修改 `pyproject.toml` 后运行：

```bash
uv lock
uv lock --check
```

提交前同时检查 `uv.lock` 差异和新增包许可证。不要只修改锁文件中的版本文本。

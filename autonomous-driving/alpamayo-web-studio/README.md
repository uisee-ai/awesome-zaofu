# Alpamayo Web Studio

Alpamayo Web Studio 是面向自动驾驶研究、场景推理和模型评测的本地工作台。产品代码位于 [`app/`](app/README.md)，需求基线位于 [`docs/prd/alpamayo-web-studio-prd.md`](docs/prd/alpamayo-web-studio-prd.md)。

- [使用教程](docs/manual/user-guide.md)
- [ZaoFu 交付案例](CASE.md)

当前实现包含可运行的 Next.js Web、FastAPI API、持久化单并发推理队列、不可变 SceneVersion、六个共享场景 Demo，以及 VQA、CoC、Meta Action 和 64 点未来轨迹展示。

## 本地启动

```bash
cd app
npm install
python -m venv .venv
.venv/bin/pip install -e backend
source .venv/bin/activate
bash deploy/scripts/run-local-studio.sh
```

默认使用确定性 mock provider，打开 `http://localhost:3000` 即可验证完整产品流程。真实 LiteLLM 配置和测试命令见 [`app/README.md`](app/README.md)。

本产品仅用于研究、评测与演示，模型输出不得直接用于真实车辆控制，也不构成安全认证。

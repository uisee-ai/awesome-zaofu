# Alpamayo Web Studio Case

## 案例定位

Alpamayo Web Studio 是面向道路场景管理、视觉语言推理、轨迹分析和回归评测的
本地工作台。已提交快照包含 Next.js Web、FastAPI API、持久化单并发队列、
不可变 SceneVersion、六个共享场景 Demo，以及 VQA、CoC、Meta Action、未来轨迹
和回归报告相关模块。

## ZaoFu 交付路径

该项目来自一次 PRD V4 多 Agent 长周期构建。任务按场景、Gateway、队列、持久化、
Web 工作台、六类 Demo、评测与发布验证拆分，由多个 impl/verify lane 接力完成。

需求入口：

- [`docs/prd/alpamayo-web-studio-prd.md`](docs/prd/alpamayo-web-studio-prd.md)
- [`README.md`](README.md)
- [`app/README.md`](app/README.md)

## 已提交快照能力

- Scene 创建、版本、生命周期、上传校验、去重和共享目录。
- Alpamayo Gateway、单并发推理队列、持久化运行记录和恢复。
- Camera ablation、VQA、自动标签、顺序评测和回归 Judge 报告。
- BEV/轨迹导出、同步相机时间线和六类 Demo 的前后端合同。
- Next.js、FastAPI、TypeScript/Python 测试和浏览器测试资产。

## 快照与打包

- 注册项目：`alpamayo-web-studio-20260809t120851z`
- 源项目：`alpamayo-web-studio-20260809t120851z`
- 源 ref：`wip/codex-20260811-alpamayo-product-hardening`
- 源 commit：`dab6f58b585688623eef89f726ab45678aa0bac5`
- 打包方式：从已提交 ref 执行 `git archive`。
- 未复制：Git 历史、`.zf-*`、`node_modules`、`.next`、dist/build、缓存和运行数据。

源工作树在该提交后仍存在未提交的 native-provider、sequence playback 和产品收口
改动；它们没有纳入本案例，也不应视为此快照已完成能力。默认 mock provider 可以
用于本地产品流程，真实 Provider 需要按 [`app/README.md`](app/README.md) 配置。

Awesome 快照验证结果：`npm run lint` 通过、TypeScript `86/86` 测试通过、Python
后端 `8/8` 测试通过。后端 `pyproject.toml` 当前只声明运行依赖；运行 Python 测试
前还需在测试环境安装 `pytest` 与 FastAPI `TestClient` 所需的 `httpx`。

## 许可证与安全

源快照没有独立许可证文件，因此本仓库不对其授予额外许可；在许可证明确前仅作为
ZaoFu 生成案例供审阅。该产品仅用于研究、评测和演示，不得用于车辆控制或安全认证。

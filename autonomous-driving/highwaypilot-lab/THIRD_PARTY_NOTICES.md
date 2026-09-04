# Third-Party Notices

本案例不重新分发依赖源码。依赖版本和许可证的事实源是本目录的
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 与锁定文件
[`uv.lock`](uv.lock)、[`package-lock.json`](package-lock.json)。

当前项目直接声明或运行时使用的关键组件包括：FastAPI、HighwayEnv、Gymnasium（由
HighwayEnv 运行链路使用）、NumPy、ONNX Runtime、Pydantic、uvicorn、Three.js、Vite、
Vitest 和 Playwright。具体版本以锁文件和 SBOM 为准，不在本材料中手工复制第二份版本表。

项目原创内容使用本目录 [`LICENSE`](LICENSE) 中的 Apache License 2.0。第三方
组件仍受各自第三方许可证约束；模型运行时和训练资产的归属记录分别位于
[`licenses/training/model-onnx.json`](licenses/training/model-onnx.json) 和
[`licenses/training/construction-dqn-v1.json`](licenses/training/construction-dqn-v1.json)。

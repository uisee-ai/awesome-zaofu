# 真实性能 spike 方法

本 spike 通过仓内固定 workload fixture 驱动本机安装的 branded Google Chrome，不访问外网或第三方数据。Playwright 使用 lockfile 固定的 `@playwright/test@1.62.1`，按官方 `BrowserType.launch({ channel: "chrome", headless: false })` API 启动桌面 Chrome。

来源：https://playwright.dev/docs/api/class-browsertype#browser-type-launch

## 固定条件

- 浏览器：Google Chrome channel `chrome`，必须 headed；不允许静默回退 bundled Chromium 或 headless。
- fixture：相邻 SHA-256 sidecar 固定原始字节。
- workload：120,000 个固定 seed 点，1280×720 viewport。
- 重复：3 个全新 Chrome process/context/page 作为 cold session；每个 session 在保留点缓存和 JIT 状态后重复 3 次 warm 操作。
- 网络：页面由 `setContent` 注入，允许 origin 列表为空；检测到任何非 about/data/blob 请求即失败。
- 工具：浏览器内 `performance.now()` 记录原始毫秒样本；runner 记录 minimum、maximum、mean、median 和 nearest-rank p95。

## 指标

- `dataset_open_ms`：生成确定性点 buffer 并计算 accumulator。
- `first_render_ms`：投影全部点并向 Canvas 绘制有界样本。
- `frame_switch_ms`：对全部点应用固定刚体变换与投影。
- `interaction_ms`：在完整 projected buffer 中寻找固定 cursor 的最近点。

报告同时记录 CPU、内存、OS、Chrome、存储、fixture digest、cold/warm 定义、重复次数和工具版本。首次运行保存 raw samples；已有 durable report 时，同一命令仍执行全部真实 Chrome 测量，但不覆盖已提交证据，以保持验证 worktree 干净。

`60s`、`3s`、`500ms`、`200ms` 仅作为 UNVERIFIED candidates 写入报告，任何观测值都不会改变命令退出状态或被升级为发布门槛。

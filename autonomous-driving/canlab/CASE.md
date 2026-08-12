# CAN Lab Case

## 案例定位

CAN Lab 是完全运行在浏览器中的 CAN 协议实验室。它使用仓库内置的合成 DBC、
验证向量和确定性 NDJSON 日志，提供 DBC 浏览、原子时间组回放、逐位解码追踪、
虚拟车辆仪表和报文健康度分析。产品离线且只接收，不连接 CAN 硬件，也不发送报文。

## ZaoFu 交付路径

1. 多角色需求讨论把产品能力、安全边界和验收标准冻结为可执行 PRD。
2. PRD Flow 按资产、DBC/解码、回放、健康指标、Web 工作区和应用装配切片实现。
3. Issue Flow 补齐浏览器兼容、真实 CSP、未知帧完整性和发布验证闭环。
4. Verify/Judge 绑定静态测试、浏览器截图、网络/存储断言和发布证据清单。

需求与产品入口：

- [`docs/prd/can-lab-p0-delivery-prd.md`](docs/prd/can-lab-p0-delivery-prd.md)
- [`README.md`](README.md)
- [`docs/manual/user-guide.md`](docs/manual/user-guide.md)

## 已验证能力

- DBC Message/Signal 浏览，以及 Intel/Motorola、signed/unsigned 和枚举解码。
- 按事件时间确定性执行 Play、Pause、Step、Seek、Loop 和倍率回放。
- 原始字节、位域、整数、缩放公式和物理值的完整 Decode Trace。
- 实际字节 SHA-256 校验，资产漂移时 fail closed。
- 未知帧原始元数据保留，不伪造 Signal 或公式链。
- 版本化被动 API 策略、HTTP CSP、零持久化和浏览器黄金旅程。

## 快照与打包

- 基线提交：`e714968db5461ce0027f586aad5f73bf31f3ed89`
- 打包方式：基于已验证工作树生成 source-only 快照。
- 未复制：Git 历史、`.zf-*`、`node_modules`、`dist`、重复 workflow 投影、
  Playwright trace、音视频成片和机器本地配置。
- 保留：源码、锁文件、合成资产、测试语料、用户指南和最小发布证据。

## 许可证与安全

仓库根许可证适用于发布者有权授权的内容；DBC 兼容测试语料沿用各自目录内的
许可证与来源清单。CAN Lab 只用于学习、研究、评测和演示，不得用于车辆控制或
安全认证。

# Sensor Workbench Case

## 案例定位

Sensor Workbench 是面向自动驾驶研究的本地多模态数据浏览和标注审核工作台。它将
nuScenes keyframe、OpenLane V1.2、坐标投影和审核差异收口为一个浏览器产品，并以仓库
内合成 fixture 提供无需第三方数据的可重复演示。

产品是只读数据根、独立审核工作区和 loopback 服务的组合：第三方数据不被修改或上传，
审核历史和导出不写回数据根。它不包含在线推理、训练、官方评测、远程协作或车辆控制。

## ZaoFu 交付路径

1. 通过 PRD Flow 冻结双 Adapter、坐标投影、审核历史和数据边界的 MVP 验收标准。
2. 按契约、nuScenes、OpenLane、review 和应用装配切片实现可运行的 Web 工作台。
3. 通过 Issue/恢复流程补齐审核持久化、差异重放、真实数据根只读和边界拒绝语义。
4. 通过类型检查、单元测试、生产构建、合成浏览器旅程和许可证扫描形成发布证据。

需求基线见 [`docs/product/sensor-workbench-mvp-prd.md`](docs/product/sensor-workbench-mvp-prd.md)，
使用入口见 [`README.md`](README.md) 和 [`docs/manual/user-guide.md`](docs/manual/user-guide.md)。

## 已验证能力

- 合成 nuScenes keyframe 的六路相机、LiDAR、BEV、时间差和实例联动。
- 合成 OpenLane 2D/3D lane 的选择、点序列、类别、可见性和属性展示。
- 审核问题创建、不可覆盖历史、差异 JSON 导出和重复导入。
- 固定坐标/投影 fixture 与数据边界测试。
- 无非回环请求的 Chromium 合成端到端旅程。
- 生产构建、锁定依赖和合成数据许可证边界检查。

## 发布快照边界

发布时只保留源码、锁文件、合成 fixture、测试、PRD、用户文档和必要的许可证/来源说明。
不应复制：

- `.zf-*`、`.codex/`、workflow 投影、事件日志和本机状态；
- `node_modules/`、`dist/`、Playwright report/trace 和临时测试结果；
- 演示视频、PPT、WPS 等发布外部的媒体源文件；
- nuScenes、OpenLane、Waymo 原始数据、模型权重或数据集压缩包。

当前工作树的最新实现仍需在发布前提交为一个干净 commit；`case.yaml` 中的 commit 字段
应替换为该发布 commit。

## 许可证与安全

原创源码和文档采用 Apache License 2.0。第三方数据仅由使用者自行取得，继续适用
nuScenes、OpenLane 和其他上游项目的许可证及使用条款。项目仅用于研究、评测和演示，
不得直接控制车辆，也不构成安全认证。

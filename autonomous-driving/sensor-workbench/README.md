# Sensor Workbench

Sensor Workbench 是一个面向自动驾驶研究与评测的本地多模态数据工作台。它把
nuScenes keyframe 浏览、OpenLane V1.2 车道浏览、跨视图选择、坐标投影和标注审核
放在同一个只读数据工作区中，帮助开发者回答：当前帧的传感器看到了什么、标注是否
对齐、目标如何随时间移动，以及审核差异能否被稳定导出和恢复。

本项目是 [Awesome ZaoFu](https://github.com/uisee-ai/awesome-zaofu) 的独立案例，
用于展示从 PRD、工程实现到浏览器验证的完整交付链路。它是本地单用户研究/演示工具，
不是量产系统、车辆控制器或安全认证产品。

## 功能概览

- 内置合成数据模式：无需下载第三方数据、无需外网即可体验双 Adapter 和审核闭环。
- nuScenes keyframe：六路相机、LiDAR、BEV、时间差、frame context 和实例联动。
- OpenLane V1.2：只读 2D/3D lane 浏览、点序列、类别、可见性和属性检查。
- 审核工作区：创建问题、评论、状态和建议，支持不可覆盖历史以及差异导出/导入。
- 数据边界：第三方数据根只读，路径穿越、符号链接和非法跨站请求会被拒绝。
- 证据模型：浏览器验证绑定构建、fixture digest、数据根前后摘要和 loopback 网络结果。

## 快速开始

要求 Node.js `>=20.19.0`。在项目根目录执行：

```bash
npm ci --prefix app
npm run dev
```

然后打开 <http://127.0.0.1:4173/>。应用默认展示仓库内的合成 nuScenes/OpenLane
fixture；页面中的相机、点云和 BEV 是可解释的合成视图，不是第三方数据的再分发。

如果需要从局部数据根读取真实数据，可在启动 Vite 前设置：

```bash
export NUSCENES_DATA_ROOT=/path/to/nuscenes
export OPENLANE_DATA_ROOT=/path/to/openlane
npm run dev
```

真实数据必须由使用者自行取得并遵守 nuScenes、OpenLane 及其依赖材料的许可证。应用只
读取本地数据根，不上传、修改或覆盖这些文件；详细边界见
[`app/docs/openlane/README.md`](app/docs/openlane/README.md)。

## 开发与验证

```bash
npm run typecheck
npm run build
npm --prefix app run test:unit
npm --prefix app run e2e:synthetic
npm run verify:license
```

浏览器测试默认启动 loopback Vite 服务。资源受限的环境可以使用
`CHOKIDAR_USEPOLLING=1 npm --prefix app run e2e:synthetic`，避免文件监听器数量限制。

## 项目文档

- [中文使用教程](docs/manual/user-guide.md)
- [ZaoFu 交付案例](CASE.md)
- [MVP PRD](docs/product/sensor-workbench-mvp-prd.md)
- [数据边界与合成数据政策](app/docs/operations/synthetic-demo-data-policy.md)
- [共享契约](app/docs/contracts/README.md)
- [公开发布清单](docs/release/publication-checklist.md)

## 数据、许可证与安全边界

仓库只包含发布者拥有或有权发布的源码、文档和合成 fixture；不包含 nuScenes、OpenLane
或 Waymo 的原始图像、点云、压缩包和数据根。项目原创内容采用 Apache License 2.0，
详见 [`LICENSE`](LICENSE)。第三方数据、模型、商标和引用文档继续适用其各自条款。

本项目仅用于研究、评测和演示。不得将其用于真实车辆控制、安全决策或替代任何安全认证。

# 第三方软件与素材声明

本目录的原创源码和文档随 `awesome-zaofu` 按 Apache License 2.0 发布。下面列出的
第三方组件、生成文件及商标继续适用各自条款；本项目不代表相关上游项目的官方产品或
获得其背书。

## 随本目录分发的内容

| 内容 | 版本/位置 | 来源 | 许可证与处理方式 |
| --- | --- | --- | --- |
| Three.js ES modules | 0.185.1，`src/scenarioforge/web/static/vendor/` | [mrdoob/three.js](https://github.com/mrdoob/three.js) | MIT；原许可证全文保存在同目录 `LICENSE.threejs.txt` |
| SUMO 路网 XML | `assets/p1/smarts/*/map.net.xml` | 本项目输入文件经 Eclipse SUMO `netconvert` 生成 | EPL-2.0（GPL-2.0-or-later 为次级选项）；本项目按 EPL-2.0 分发这些生成文件 |
| ScenarioForge Sedan v1 | `src/scenarioforge/web/static/app.js` | 本项目原创程序化模型 | CC0-1.0；声明与摘要见 `assets/p1/replay/vehicle-model-manifest.json` |
| 场景配置与示例 JSON/XML | `assets/`、`examples/` | 本项目原创合成场景 | Apache-2.0；不包含真实道路、客户数据或第三方数据集 |

## 由安装工具取得、未作为源码打包的运行依赖

- MetaDrive 0.4.3：Apache-2.0。
- SMARTS 2.0.1：MIT。
- Eclipse SUMO 1.19.0：EPL-2.0，GPL-2.0-or-later 为次级选项。
- PyYAML：MIT；jsonschema：MIT；Starlette 与 Uvicorn：BSD-3-Clause；
  Playwright：Apache-2.0；pytest：MIT。

完整、精确的依赖版本以 `uv.lock` 为准。锁文件只记录包的解析结果，并不把这些包的
源码重新授权为 Apache-2.0。部署者仍应在自己的发行形式中检查依赖、系统库和浏览器
二进制的许可证义务。

## 未包含内容

本发布快照不包含 MetaDrive、SMARTS 或 SUMO 的源码归档，不包含模型权重、真实地图、
真实车辆数据、客户数据、Playwright trace、演示视频或 ZaoFu 私有运行日志。

官方许可证参考：

- MetaDrive：<https://github.com/metadriverse/metadrive/blob/main/LICENSE.txt>
- SMARTS：<https://github.com/huawei-noah/SMARTS/blob/master/LICENSE>
- Three.js：<https://github.com/mrdoob/three.js/blob/dev/LICENSE>
- Eclipse SUMO：<https://eclipse.dev/sumo/docs/Downloads.html#note-on-licensing>

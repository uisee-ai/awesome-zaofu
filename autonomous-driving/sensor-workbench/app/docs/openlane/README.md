# OpenLane V1.2 只读浏览边界

本 feature 只负责 OpenLane V1.2 的数据根扫描、annotation 解析和 2D/3D lane 联动浏览。它不会修改第三方数据根，也不执行官方评测或模型训练。

## 数据获取与许可

OpenLane V1.2 基于 Waymo Open Dataset。使用真实数据前，用户必须先在 Waymo Open Dataset 注册并接受其条款，再通过 OpenLane 官方 download request form 获取数据。OpenLane 官方将数据声明为 CC BY-NC-SA，并同时受 Waymo Dataset License Agreement for Non-Commercial Use (August 2019) 约束；因此本产品明确标示 **Non-Commercial Use**，不得把数据用于商业用途。仓库代码本身采用官方仓库所述的 Apache-2.0 许可，代码许可不改变数据许可。

权威来源固定到实现时核验的 OpenDriveLab commit `ec98fda7cb21ecf51ffdf70c37c411076985dbd6`：

- [OpenLane V1 README 与获取/许可说明](https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/README.md)
- [2D/3D lane annotation 字段与类别表](https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/anno_criterion/Lane/README.md)
- [坐标系与 V1.2 pose 说明](https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/data/Coordinate_Sys.md)

## 只读与脱敏规则

- scanner 只使用目录遍历、metadata 与文件读取操作；遇到 symlink 会 fail closed。
- 扫描前后对排序后的相对文件名与文件内容摘要做 SHA-256 汇总，交付 audit 必须保持前后一致。
- 原始媒体不会进入源码仓库、workspace 或 evidence receipt。synthetic fixture 只包含人工构造的 JSON annotation，不包含 OpenLane/Waymo 图像。
- receipt 只保留数据根摘要、文件计数、布尔边界和 redacted artifact digest；不保留绝对路径或媒体字节。
- index、cache、review 与 evidence 的任何可变输出只能由 assembly 写入独立 workspace/output。

## V1.2 解析与 fallback

解析器完整消费 `intrinsic`、`extrinsic`、`pose`、`file_path` 和每条 lane 的 `category`、`visibility`、`uv`、`xyz`、`attribute`、`track_id`。`visibility`、2D 和 3D 点数必须完全相同；frame 内 `track_id` 必须唯一。2D/3D 视图从同一个 `laneRef` 派生 `:2d`/`:3d` reference，因此一次选择会同时更新两视图。

V1 reader 对未知未来字段执行 `ignoredSourceFields` 策略；不支持的数据版本、绝对/越界路径、非法类别/属性、数组长度漂移或 symlink 数据根会明确报错。共享 Adapter v1 中未实现的模型对比、官方评测和原始数据修改使用 `report_unsupported` fallback。

## Synthetic fixture 与 assembly 接线

fixture root digest 为 `sha256:f63d05a3772587bc3cbc80091d62ed538bb5f885025eebc127677c512dc302f6`。它固定两条 lane 的完整类别、点序列、可见性和属性，同时保留一个未知 future 字段验证 ignored 行为。

assembly 应在 `/openlane` 接线 `OpenLaneFeature`，并保持 `app/tests/e2e/specs/openlane.spec.ts` 中的 `data-testid` 和 evidence binding。真实浏览器 runner 负责提供最终 `evidence-receipt.v1`，绑定 command、commit、production build、runner/browser、fixture digest、时间、退出状态、前后数据根摘要、redacted artifacts 与 loopback-only network 结果。

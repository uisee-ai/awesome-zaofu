# 坐标 spike 方法

本 spike 使用仓内合成黄金 fixture，不包含或再分发任何第三方数据。fixture 原始字节由相邻 `.sha256` sidecar 固定；digest 不匹配时 runner fail-closed，不使用更新后的未知输入继续测量。

## 权威坐标约定

- nuScenes devkit `d9de17a73bdc06ce97a02f77ae7edb9b0406e851`：点从 LiDAR sensor 依次变换到 LiDAR 时刻 ego、global、camera 时刻 ego、camera；camera-frame `z` 是 depth，使用相机内参投影并按 depth 归一化。
- OpenLane `ec98fda7cb21ecf51ffdf70c37c411076985dbd6`：V1.2/Waymo camera frame 为 x-front、y-left、z-up；标准 camera frame 为 x-right、y-down、z-front，因此映射为 `[-y, -z, x]`。

来源：

- https://github.com/nutonomy/nuscenes-devkit/blob/d9de17a73bdc06ce97a02f77ae7edb9b0406e851/python-sdk/nuscenes/nuscenes.py
- https://github.com/nutonomy/nuscenes-devkit/blob/d9de17a73bdc06ce97a02f77ae7edb9b0406e851/python-sdk/nuscenes/utils/geometry_utils.py
- https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/data/Coordinate_Sys.md

## 测量

- 4×4 变换矩阵按 row-major 存储，点按齐次列向量 `[x,y,z,1]` 处理。
- 3D residual 为 expected/actual 三维点的欧氏距离（米）。
- projection residual 为 expected/actual 像素点的二维欧氏距离（像素）。
- 非正 depth 不执行除法，返回 `not_projected` fallback。
- fixture 中列出的未知未来字段和 MVP 排除模态保持 ignored，不静默映射为已支持能力。
- `1e-5m` 与 `0.5px` 仅记录为 UNVERIFIED candidates；runner 的成功条件是 fixture 完整、digest 正确、方法可执行且报告可生成，不以候选值作门槛。

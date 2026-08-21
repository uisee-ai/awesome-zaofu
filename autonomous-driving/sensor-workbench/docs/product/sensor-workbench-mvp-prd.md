# Sensor Workbench 双数据源审核 MVP canonical PRD r5

- Canonical revision: `5`
- Canonical SHA-256: `2799455a9649b7ef3a37b463dcd560b27d0d011046c70ea56e47ecf0595771e9`
- Scope: frozen

## 产品范围

本机单用户产品支持 nuScenes keyframe 多模态浏览、OpenLane V1.2 只读 2D/3D 车道浏览、场景检索、坐标投影、标注审核、历史和差异导出。第三方数据不修改、不上传、不再分发；所有服务仅监听 loopback。

范围内能力：

- nuScenes keyframe 多模态浏览与传感器时间差
- OpenLane V1.2 只读 2D/3D 车道浏览
- 场景检索与有来源标识的派生筛选
- 坐标转换与投影
- 标注审核、不可覆盖历史和差异导入导出
- 本机单用户 loopback 服务

## 冻结决策

- OpenLane 只读 Adapter 与 2D/3D 车道浏览属于 MVP。
- 标注审核和差异记录属于 MVP。
- 离线模型结果对比和 OpenLane 官方评测入口不属于 MVP。
- nuScenes 只浏览 keyframe 并展示传感器时间差，不覆盖非关键帧 sweep。
- BEV 不包含 HD 语义地图。
- 允许带来源标识的派生天气与昼夜标签。
- 性能测量基线为 8 核 CPU、16GB 内存、桌面 Chrome 和 nuScenes mini。
- 审核、索引、缓存和导出写入独立应用工作区，第三方数据根始终只读。
- OpenLane 数据由用户自行取得；商业用途须另行完成许可审核。

## 数值候选政策

`60s`、`3s`、`500ms`、`200ms`、`1e-5m`、`0.5px` 均为 UNVERIFIED candidates。技术 spike 只记录固定环境、fixture、方法、原始样本和统计摘要；未经受控 PRD revision，这些数值不构成通过门槛。

## 不在范围内

- 模型预测对比与在线推理
- OpenLane 官方评测和训练环境
- nuScenes 非关键帧与多 sweep
- Radar、lidarseg、panoptic 和 CAN bus
- HD Map 与车道拓扑地图
- 远程、多用户和云端协作
- 修改或覆盖第三方标注
- 第三方数据再分发

## Acceptance Criteria

- AC-01 When 合成样例启动, the system shall 在无第三方数据和无外网条件下运行双 Adapter 基本界面与审核闭环。
- AC-02 When 数据根被扫描, the system shall 识别版本、缺失资产和受影响范围，且不泄露绝对路径。
- AC-03 When nuScenes keyframe 被选择或快速跳转, the system shall 保持统一 frame_context_id、显示 timestamp/delta 并丢弃过期响应。
- AC-04 When 坐标 spike 执行, the system shall 以固定黄金 fixture 和测量方法验证转换与投影；1e-5m/0.5px 仅作为待证候选。
- AC-05 When nuScenes instance 被选择, the system shall 在相机、LiDAR、BEV 和当前 scene 标注链中保持一致引用。
- AC-06 When 检索或派生筛选执行, the system shall 返回与索引一致的结果，并保存原文、derived 标记及规则版本。
- AC-07 When OpenLane V1.2 fixture 被打开, the system shall 正确联动 2D/3D lane reference、类别、点序列、可见性和属性。
- AC-08 When 审核记录被创建或更新, the system shall 持久化问题、评论、状态、建议和不可覆盖历史。
- AC-09 When 差异被导出并重新导入, the system shall 恢复相同审核语义、稳定去重且不包含原始媒体或绝对路径。
- AC-10 When 路径穿越、编码绕过、符号链接逃逸、非法 Host/Origin 或跨站写请求发生, the system shall 拒绝并生成脱敏日志。
- AC-11 When 性能 spike 执行, the system shall 输出固定环境和 fixture 下的原始测量、重复结果及统计摘要；60s/3s/500ms/200ms 仅为候选。
- AC-12 When 许可证检查执行, the system shall 证明仓库、安装包、fixture 和合成样例不含 nuScenes/OpenLane/Waymo 原始数据。
- AC-13 When 浏览、审核和导出完成, the system shall 证明第三方数据目录文件摘要未变化。
- AC-14 When 正常浏览运行, the system shall 无非回环数据请求，并遵守点云分块、LOD、Worker 和明确缓存上限。

## 风险和依赖

- OpenLane 的 Waymo 与非商业条款需要持续许可门禁。
- nuScenes/OpenLane 坐标语义差异可能造成目标或车道错位。
- 审核历史是不可丢失状态，需要迁移、备份、故障恢复和确定性重放测试。
- 数值硬门槛尚未冻结，后续冻结依赖坐标与真实性能 spike 的受控证据。

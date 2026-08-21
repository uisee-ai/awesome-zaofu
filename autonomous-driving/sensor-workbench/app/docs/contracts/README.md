# Sensor Workbench 共享契约

`app/src/contracts/` 是下游任务共同消费的不可变 v1 边界。破坏兼容性的字段、枚举或 wire naming 变更必须回流 `SWB-SPIKE-001`，并通过受控 PRD/contract revision 处理；feature slice 不得自行改写。

约定如下：

- TypeScript 内部对象使用 `camelCase`，持久化、导出和 receipt wire 对象使用 `snake_case`。
- 所有持久化对象携带字面量 `schema_version`；v1 reader 对未知字段采取 forward-compatible ignore，对缺少必填字段采取 fail-closed。
- 时间戳使用 UTC RFC 3339 字符串；数据时间使用整数微秒，传感器偏差使用毫秒。
- 数据根只读且不得进入 API、日志、导出或 evidence；可变状态只写独立 workspace/output。
- ID 是稳定、不透明且非空的字符串。digest 使用 `sha256:<64 lowercase hex>`。

完整 frozen scope、14 条 canonical AC、候选阈值政策及目录约定见 `scaffold-contract.v1.json`。

# v1 wire contract

下游代码从 `app/src/contracts/index.ts` 导入类型、版本常量和显式转换函数。内部对象使用 camelCase；持久化、导出和 evidence 使用 snake_case。转换函数逐字段构造结果，避免隐式 key-case 转换把未知字段带入稳定格式。

v1 reader 的兼容规则：

- 必填字段缺失、版本不符、枚举越界或只读约束冲突时 fail-closed。
- 未知顶层或嵌套字段被忽略，允许 v1 reader 读取增加可选字段的后续 producer 输出。
- `sensor_frames` 是完整、有序的传感器列表；每项都携带 `timestamp_us` 与相对 frame 时间的 `delta_ms`，缺失资产以 `availability=missing` 和 `asset_ref=null` 成对表达。
- Adapter 明确列出 capabilities、unsupported capabilities、fallback behavior 与 ignored source fields，禁止静默假装支持。
- passed evidence 必须同时满足 `exit_code=0`、数据根前后 digest 相同、仅 loopback 网络且无非回环请求。
- export 永远要求 `media_included=false`、`absolute_paths_included=false`，并要求 event、identity 和 `event_count` 完整一致。

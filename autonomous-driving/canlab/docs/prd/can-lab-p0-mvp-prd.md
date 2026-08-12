# ZaoFu CAN Lab P0 MVP 实施就绪 PRD

## Source Requirement
@all CANLAB_PRD_CHANNEL_20260803. Create and start a three-round PRD clarification Channel for the Zaofu CAN Lab P0 MVP. Use the fixed PRD clarification team: product_pm, arch, critic, synthesizer, and include the optional security_reviewer because the domain is vehicle CAN. The canonical PRD must be implementation-ready and cover these owner constraints: 1) browser DBC explorer for a bundled demo DBC with message/signal hierarchy, search, bit layout, scale, offset, unit, enum, source/version/license, and deterministic validation; 2) one documented offline CAN log format plus deterministic seeded synthetic drive-cycle data for start, acceleration, cruise, turn, deceleration, and stop; 3) replay controls for play, pause, step, speed, seek, and loop, with raw bytes, decoded physical values, unknown-frame states, stale/drop/frequency indicators, trends, and a virtual dashboard; 4) traceability from raw frame through DBC signal definition to displayed physical value; 5) a small locally runnable Node/TypeScript product with build, unit tests, and one browser E2E; 6) synthetic/offline and passive-only scope: no real vehicle connection and no CAN transmit path. Debate product scope, frontend interaction, backend/domain model, safety boundary, testability, and delivery slicing. After exactly three rounds, the synthesizer must propose one canonical PRD for owner confirmation. Do not start implementation or a workflow before owner confirmation.

## Requirement
交付一个面向 CAN 学习者和开发者的本地 TypeScript SPA。用户可浏览内置合成 DBC、搜索消息与信号、回放固定 NDJSON 驾驶日志、查看原始帧、解码物理值、健康指标、趋势及虚拟仪表，并从任一已知显示值追溯到原始字节和 DBC 换算定义。Node 仅负责构建、测试和 loopback 静态服务；解析、回放、解码、追踪与仪表投影均由浏览器内纯 TypeScript 领域模块完成。D-06 是 Step 粒度的唯一规范，D-08 是 expectedPeriodUs 来源的唯一规范。

## Decisions
- {"decision":"首要用户是 CAN 学习者和开发者，不承诺生产车辆标定工具兼容性。","id":"D-01","question_refs":["q-6478f1c9849a7b63"],"status":"resolved"}
- {"decision":"产品为纯浏览器 SPA；无业务后端、数据库或外部服务，Node 仅用于构建、测试和本地静态服务。","id":"D-02","question_refs":["q-cfd00323add4e4b7","q-43594e46f94799c4","q-57325d3067f6da83"],"status":"resolved"}
- {"decision":"P0 只读内置资产，不支持导入、编辑、导出或保存。演示 DBC 为项目自有合成资产 v1.0.0，采用 SPDX CC0-1.0，并附来源声明、SHA-256 和黄金验证向量。","id":"D-03","question_refs":["q-1298281647269f89","q-5db7571d785ec29c","q-b530e369ddf52010","q-de503f7a8d196847","q-c7f1391eb23c7a0f"],"status":"resolved"}
- {"decision":"DBC 兼容范围仅为演示文件使用的显式子集：标准及扩展 ID、Intel/Motorola、signed/unsigned、factor、offset、unit 和 enum；其他构造确定性 fail closed。","id":"D-04","question_refs":["q-91785eeb4e5eef6b"],"status":"resolved"}
- {"decision":"唯一日志格式为 NDJSON：首条 metadata 声明 schema、seed、scenario、整数微秒时间基准和资产版本；frame 记录包含原始 seq、timestamp_us、CAN ID、DLC 与十六进制数据。","id":"D-05","question_refs":["q-40b3e82fa40b44fc"],"status":"resolved"}
- {"decision":"唯一规范：领域状态仅使用离散事件时间；speed 只控制墙钟调度。Step 原子推进下一组相同 timestamp_us 的帧，组内按原始 seq 稳定排序。","id":"D-06","question_refs":["q-83ca4e8a6d558bf5","q-2eb9ecc85160a0f0"],"status":"normative_resolved_by_owner"}
- {"decision":"已知帧展示 raw bytes、消息/信号定义、位域、字节序、原始整数、scale/offset、物理值、单位/枚举及最终显示值；未知帧仅展示原始元数据和未知原因。","id":"D-07","question_refs":["q-ffc87a462eb731c7"],"status":"resolved"}
- {"decision":"唯一规范：stale、inferred drop 和 frequency 只按回放事件时间计算。DBC 消息周期属性是 expectedPeriodUs 唯一规范源；manifest 仅镜像，值不一致时加载失败。","id":"D-08","question_refs":["q-09599ba62680e045","q-a26fa5f59915b304"],"status":"normative_resolved_by_owner"}
- {"decision":"固定仪表为车速、转速、挡位、油门、制动和左右转向；固定趋势信号为 VehicleSpeed、EngineRpm、ThrottlePosition、BrakePressure、SteeringAngle 与 SelectedGear。","id":"D-09","question_refs":["q-5aff48b631f55e70","q-7e9a9cf6044f0dab","q-9ea87b8ad14a9727"],"status":"resolved"}
- {"decision":"运行期除 loopback 静态服务外禁止网络访问，不写浏览器持久存储；生产代码、依赖和 UI 不得包含真实 CAN 接收、硬件适配或发送路径。","id":"D-10","question_refs":["q-83cc0bba9fd8dd5c","q-9e1c224d18b24e9a","q-ce4722d7296c02d7"],"status":"resolved"}
- {"decision":"正式验收基线为最新稳定版桌面 Chromium；唯一浏览器 E2E 覆盖完整黄金旅程，边界状态由单元和集成测试覆盖。","id":"D-11","question_refs":["q-6f42bfdd153f2d99","q-fe02ff51f4ae8f3f","q-1510af7f78bd2992"],"status":"resolved"}
- {"decision":"以下紧随的两条原始 ledger 文本仅为历史审计引用，均为 SUPERSEDED / NON-NORMATIVE，不得覆盖 D-06 或 D-08，也不得作为实现、测试或验收合同。","id":"D-12","question_refs":["critic-artifact-consistency-1"],"status":"resolved"}
- 回放的“单步”是否定义为按稳定排序精确前进一个 CAN 帧？: 是；按日志时间戳及原始序号稳定排序，每次前进一帧，并在界面显示当前帧位置。
- stale、drop 和 frequency 是否采用 PRD 中固定且可计算的定义？: 是；由数据集 manifest 声明每个消息的期望周期，并固定窗口、阈值、缺帧算法及跳转后的状态重建方式。
- P0 是否明确不设常驻后端服务？: 是；采用静态浏览器应用加 Node 构建、测试工具，解码与回放由纯 TypeScript 领域模块在客户端完成。
- P0 是否锁定一个明确的仪表盘与趋势信号清单？: 锁定 6–8 个覆盖既定驾驶阶段的代表信号、固定组件类型和固定趋势窗口；自定义布局与任意图表留到 P1。
- 是否采用日志离散时间戳作为唯一规范回放时钟？: 采用离散事件时间；speed 只控制事件时间到墙钟的映射，step 按事件索引推进，seek 和 loop 的状态重建规则写入验收标准。
- 能否提供 bundled demo DBC 的来源、版本、许可证和可再分发证据？: 可以；采用项目自有、完全合成、固定版本 v1.0.0 的演示 DBC，仓库内保存 SPDX CC0-1.0 许可证、来源声明（project-authored synthetic fixture）、内容 SHA-256 和确定性验证向量。
- 是否将追踪验收拆为已知帧完整解码链和未知帧诊断链？: 是；已知帧展示 raw bytes、消息/信号、位域与字节序、原始整数、scale/offset、物理值、单位/枚举和最终显示值；未知帧仅展示原始元数据与未知原因。
- 唯一浏览器 E2E 是否固定为一条端到端关键旅程？: 固定覆盖加载 fixture、搜索信号、检查位布局、执行回放控制、验证解码追踪及仪表盘更新；边界状态由单元/集成测试补足。
- 无硬件与无发送路径应由哪些自动化负面验收证明？: 生产代码与依赖中不得存在 SocketCAN、WebSerial、WebUSB、硬件适配器或发送命令入口；构建和 E2E 必须完全离线，并增加架构级负面检查。
- Owner 是否接受 NDJSON 作为唯一 P0 离线日志格式？: 接受；首条 metadata 记录声明 schema、seed、scenario 和时间基准，后续 frame 记录包含序号、整数微秒时间戳、CAN ID、DLC 与十六进制数据。
- Owner 是否接受将虚拟仪表限定为车速、转速、挡位、油门、制动和左右转向状态？: 接受该最小集合；其余信号仅在通用趋势和详情视图展示。
- Owner 是否接受 P0 为本地 Node 工具链提供的纯浏览器应用，不设置业务后端、数据库或外部服务？: 接受；DBC 解析、日志回放和信号解码均在浏览器内完成，Node 仅用于构建、测试和本地静态服务。
- Owner 是否接受使用项目自有、完全合成且固定版本与哈希的演示 DBC？: 接受；随库提供 SPDX 许可证、来源说明、语义版本、内容哈希和确定性验证向量。
- Owner 是否接受按 DBC 消息周期和回放时间定义 stale、drop 与 frequency？: 接受；以 DBC 周期属性为基准，stale 在超过两个周期未更新时触发，drop 由超周期帧间隔推断，frequency 按回放时间的固定一秒窗口计算，并明确窗口边界与取整规则。
- Owner 是否接受桌面 Chromium 作为 P0 唯一浏览器验收基线？: 接受；P0 保持标准 Web API 与响应式基础布局，但不承诺移动端或跨浏览器认证。
- P0 是否仅允许读取随产品发布的 DBC 和合成日志，而不支持任意用户文件导入？: 是；P0 采用 bundled-only。若 owner 要求导入，应限定为浏览器文件选择、客户端内存解析、固定大小/帧数/字符串长度上限，且不得把路径或内容提交给 Node 服务。
- “offline”是否定义为运行期仅允许访问本机 loopback 静态服务，并禁止所有非 loopback 请求？: 是；禁止遥测、CDN、远程 DBC/日志、远程更新和代理接口，并以 CSP connect-src 'none' 或等效控制及 E2E 网络断言验证。
- P0 的回放数据、解析结果和历史状态是否全部限定为会话内存，不写入浏览器持久存储或服务器文件？: 是；P0 不持久化数据或回放历史，重新加载恢复到固定初始状态。
- P0 虚拟仪表的最低集合是否固定为车速、转速、挡位及左右转向指示？: 是；其他信号通过解码表和趋势图展示，不扩展为完整座舱仿真。
- P0 是否以正在学习或调试 CAN 解码的技术用户作为首要用户，而非生产车辆标定工程师？: 是；采用技术学习者/开发者定位，优先展示可理解、可验证的解码因果链，不承诺生产工具兼容性。
- P0 的正式浏览器验收是否限定为最新稳定版桌面 Chromium？: 是；本地 Node 服务加桌面 Chromium 为验收基线，其他现代浏览器仅尽力兼容。
- P0 是否限定为只读的内置 DBC 与内置合成日志，不支持用户导入、编辑或保存文件？: 是；P0 仅交付内置版本化资产，导入、编辑、导出和持久化列为非目标。
- “drop”是否定义为依据预期周期推断的缺帧数，而不是声称观测到真实总线丢包？: 定义为 inferred missing frames，仅对具有 expectedPeriodUs 的消息计算；无周期时显示 N/A，并与 stale 状态分开。
- Step 操作应前进到下一帧，还是原子处理下一组相同时间戳的帧？: 按下一组相同时间戳帧原子前进；UI 明示本次处理帧数。
- P0 是否确认不设应用后端，Node 只用于构建、测试和本地静态服务？: 确认；使用静态 TypeScript SPA，解析、回放和解码全部在浏览器内完成，不引入服务端状态。
- P0 是否仅加载随产品发布的 demo DBC 与合成 trace，不提供任意本地文件导入？: 确认仅 bundled assets；公开并测试格式，但把用户文件导入留到 P1。
- DBC 支持是否限定为 demo 文件实际使用的显式子集，而不宣称完整 DBC 兼容？: 限定子集；至少覆盖标准/扩展 ID、Intel/Motorola、signed/unsigned、factor、offset、unit 和 enum，遇到不支持构造时 fail closed 并给出确定性错误。
- 能否删除或明确标记所有被 Owner 最终裁决覆盖的旧问答为 superseded/non-normative，使 D-06 与 D-08 成为 Step 粒度和 expectedPeriodUs 来源的唯一规范定义？: 是。下一版删除 Decisions 下并列的冲突旧问答，或将其明确标记为 superseded/non-normative；D-06、D-08 与 owner 最终裁决消息是 Step 粒度和 expectedPeriodUs 来源的唯一规范定义。历史分歧只保留在 Dissent 中，不得作为实现合同。

## Assumptions
- {"assumption":"演示数据采用 Classical CAN、DLC 不超过 8。","id":"A-01","risk":"CAN FD 与生产 DBC 方言需要独立扩展合同。"}
- {"assumption":"速度控件采用 0.25x、0.5x、1x、2x 和 4x 固定档位。","id":"A-02","risk":"任意倍率会增加输入约束和调度测试。"}
- {"assumption":"固定 fixture 包含未知 ID 和受控缺帧区段，以确定性演示 unknown、stale 与 inferred drop。","id":"A-03","risk":"缺少这些帧型会使异常 UX 无法通过 E2E 证明。"}
- {"assumption":"P0 性能目标仅覆盖随包 fixture，不承诺任意大型日志。","id":"A-04","risk":"浏览器主线程性能不得被宣传为通用日志处理能力。"}

## Out of Scope
- 真实车辆、CAN 适配器、SocketCAN、WebSerial、WebUSB、实时只读接收和 CAN 发送
- 用户 DBC 或日志导入、编辑、导出、保存及跨会话持久化
- 业务后端、数据库、认证、云同步、遥测、CDN、远程更新和非 loopback 请求
- 完整 DBC 方言、demo 未使用的 multiplexing 和 CAN FD
- 生产车辆标定、安全关键决策和真实总线丢包诊断
- 自定义仪表布局、任意图表、移动端和跨浏览器认证

## Acceptance Criteria
- {"criterion":"When 应用启动时，CAN Lab shall 仅加载随包 DBC 与 NDJSON fixture，并在无外网环境完成全部核心功能。","id":"AC-01","source_refs":["q-cfd00323add4e4b7","q-5db7571d785ec29c","q-83cc0bba9fd8dd5c"]}
- {"criterion":"When 用户浏览或搜索 DBC 时，CAN Lab shall 展示消息/信号层级，并支持按名称和 CAN ID 搜索；信号详情 shall 展示 64 位布局、start bit、length、byte order、signedness、factor、offset、unit 和 enum。","id":"AC-02","source_refs":["q-91785eeb4e5eef6b","message:msg-plan-0e52281f36e8982621451543"]}
- {"criterion":"When 用户查看 DBC 资产信息时，CAN Lab shall 展示 project-authored synthetic fixture、v1.0.0、CC0-1.0、SHA-256 和验证向量版本。","id":"AC-03","source_refs":["q-c7f1391eb23c7a0f","q-de503f7a8d196847"]}
- {"criterion":"When DBC 校验运行时，CAN Lab shall 对标准/扩展 ID、Intel/Motorola、signed/unsigned、缩放、偏移、单位和枚举产生黄金结果；未支持构造 shall 返回稳定错误且不部分解码。","id":"AC-04","source_refs":["q-91785eeb4e5eef6b"]}
- {"criterion":"When 使用相同 schema、DBC 版本和 seed 生成 fixture 时，生成器 shall 产生字节相同的 NDJSON 与 SHA-256，并覆盖 start、acceleration、cruise、turn、deceleration 和 stop。","id":"AC-05","source_refs":["q-40b3e82fa40b44fc","message:msg-plan-0e52281f36e8982621451543"]}
- {"criterion":"When 用户执行 play、pause、speed、seek 或 loop 时，ReplayEngine shall 仅按整数微秒事件时间改变领域状态；墙钟抖动不得改变帧顺序、解码值、趋势或健康指标。","id":"AC-06","source_refs":["q-83ca4e8a6d558bf5"]}
- {"criterion":"When 用户执行 Step 时，ReplayEngine shall 原子处理下一组相同 timestamp_us 的帧，按原始 seq 稳定排序，并显示组内帧数和当前位置。","id":"AC-07","source_refs":["q-2eb9ecc85160a0f0","message:msg-8693a023e292"]}
- {"criterion":"When 用户 seek 到 T 时，ReplayEngine shall 重建所有 timestamp_us <= T 的状态并暂停；When loop 回到开头时，shall 清空并从头重建状态。","id":"AC-08","source_refs":["q-83ca4e8a6d558bf5"]}
- {"criterion":"When 选中已知帧信号时，CAN Lab shall 通过稳定的 log-hash/frame-seq/signal-id 展示 raw bytes、DBC 位域、原始整数、换算公式和最终值；When 帧未知时，shall 不构造信号链。","id":"AC-09","source_refs":["q-ffc87a462eb731c7"]}
- {"criterion":"When 消息具有 DBC 周期 P 时，HealthMetrics shall 在 replayTimeUs-lastSeenUs > 2P 时标记 stale，以 max(0,floor(deltaUs/P)-1) 标记 inferred missing frames，并以 (T-1000000,T] 窗口帧数计算 frequency；无 P 时 stale 与 drop shall 显示 N/A。","id":"AC-10","source_refs":["q-09599ba62680e045","q-a26fa5f59915b304"]}
- {"criterion":"When manifest 镜像周期与 DBC 周期属性不一致时，加载器 shall fail closed；seek 与 loop 后所有 HealthMetrics shall 从规范事件历史重建。","id":"AC-11","source_refs":["q-a26fa5f59915b304","message:msg-8693a023e292"]}
- {"criterion":"When 回放推进、seek 或 loop 时，固定仪表和六条固定趋势 shall 从同一 DashboardProjection 更新，趋势横轴 shall 使用回放事件时间。","id":"AC-12","source_refs":["q-7e9a9cf6044f0dab","q-9ea87b8ad14a9727"]}
- {"criterion":"When 执行安全负向检查时，生产代码、依赖和 UI shall 不包含 SocketCAN、WebSerial、WebUSB、硬件适配器、发送命令或实时输入入口。","id":"AC-13","source_refs":["q-ce4722d7296c02d7"]}
- {"criterion":"When 浏览器 E2E 运行时，网络拦截 shall 观测到零个非 loopback 请求，CSP 或等效策略 shall 禁止远程连接，浏览器持久存储 shall 保持未写入。","id":"AC-14","source_refs":["q-83cc0bba9fd8dd5c","q-9e1c224d18b24e9a"]}
- {"criterion":"When 执行单元与集成测试时，测试 shall 覆盖 DBC 正反例、生成器字节确定性、解码黄金向量、回放状态转换、seek/loop 重建、健康指标边界和未知帧。","id":"AC-15","source_refs":["q-1510af7f78bd2992","q-91785eeb4e5eef6b"]}
- {"criterion":"When 执行唯一 Chromium E2E 时，测试 shall 加载 fixture、搜索信号、检查位布局、操作全部回放控件，并验证解码追踪、异常状态和仪表更新。","id":"AC-16","source_refs":["q-1510af7f78bd2992","q-6f42bfdd153f2d99"]}
- {"criterion":"When 提交交付候选时，npm run lint、npm test、npm run build 与浏览器 E2E shall 全部通过，并保存 verification evidence。","id":"AC-17","source_refs":["message:msg-plan-0e52281f36e8982621451543","AGENTS.md#Verification","AGENTS.md#Harness-Health-Signals"]}

## Risks
- Motorola 位编号和 signed 解码容易出现表面合理但错误的结果，必须使用黄金位级向量。
- inferred drop 不是真实总线丢包；UI 必须保留 inferred 标签。
- 纯浏览器架构处理超出随包 fixture 的大型日志时可能阻塞主线程。
- 未来依赖、遥测或设备 API 可能侵蚀离线和无硬件边界，负向检查必须成为持续 gate。
- 开发服务器不得演化为业务后端；生产构建只能提供静态资产。
- artifact renderer 会投影 resolved 问答；D-12 的 SUPERSEDED / NON-NORMATIVE 标记必须保留，避免旧答案重新成为实现合同。

## Dissent
- {"normative_ruling":"D-06：每次原子推进下一组相同 timestamp_us 帧，组内按原始 seq 稳定排序。","resolution_refs":["message:msg-8693a023e292","question:critic-artifact-consistency-1"],"status":"superseded_non_normative","superseded_position":{"position":"每次前进一个 CAN 帧。","source":"q-16e7b2017db5de0f"},"topic":"Step 粒度历史分歧"}
- {"normative_ruling":"D-08：DBC 消息周期属性为唯一规范源；manifest 仅镜像且不一致时 fail closed。","resolution_refs":["message:msg-8693a023e292","question:critic-artifact-consistency-1"],"status":"superseded_non_normative","superseded_position":{"position":"由数据集 manifest 声明。","source":"q-6db2c83b91a64c1a"},"topic":"expectedPeriodUs 来源历史分歧"}

## Open Questions
- None.

## Recommended Workflow
```json
{
  "authorization": "not_started",
  "preconditions": [
    "product_pm、arch、critic 和 security_reviewer 对修订 artifact 完成签收",
    "Owner 确认 canonical PRD",
    "Owner 另行授权创建 Task 或启动 Workflow"
  ],
  "required_gates": [
    "npm run lint",
    "npm test",
    "npm run build",
    "browser E2E",
    "DBC provenance and checksum verification",
    "offline/passive-only negative verification"
  ],
  "stages": [
    {
      "deliverables": [
        "DBC v1.0.0、CC0-1.0、来源与 SHA-256",
        "NDJSON schema、种子生成器与黄金 fixture",
        "禁止网络、硬件和发送路径的静态 gate"
      ],
      "depends_on": [],
      "id": "S1",
      "name": "合同、合成资产与安全边界"
    },
    {
      "deliverables": [
        "DBC 子集解析与验证",
        "ReplayEngine 与 seek/loop 状态重建",
        "DecodeTrace、HealthMetrics 和黄金单元测试"
      ],
      "depends_on": [
        "S1"
      ],
      "id": "S2",
      "name": "纯 TypeScript 领域核心"
    },
    {
      "deliverables": [
        "DBC explorer、搜索和位布局",
        "回放控件、帧表和追踪面板",
        "固定 dashboard、trends 和异常状态"
      ],
      "depends_on": [
        "S2"
      ],
      "id": "S3",
      "name": "浏览器交互闭环"
    },
    {
      "deliverables": [
        "唯一 Chromium 黄金旅程 E2E",
        "离线、无持久化和无硬件负向验证",
        "lint、unit、build 与 E2E gate evidence"
      ],
      "depends_on": [
        "S3"
      ],
      "id": "S4",
      "name": "集成、E2E 与交付证据"
    }
  ],
  "status": "recommended_only_awaiting_prd_confirmation",
  "type": "controlled_zaofu_dag"
}
```

## Provenance
- Channel: `ch-prd-clarification-2621451543`
- Thread: `main`
- Source: `event:evt-18e8d6c569d1`
- Source: `event:evt-af2c126995c8`
- Source: `event:evt-13577a04e678`
- Source: `event:evt-f10830a6a3d0`
- Source: `event:evt-9dfc44826133`
- Source: `event:evt-09f824348db0`
- Source: `event:evt-a42bf0b2ef88`
- Source: `event:evt-19a5e47a87c0`
- Source: `event:evt-584a9bd98cfa`
- Source: `message:msg-plan-0e52281f36e8982621451543`
- Source: `message:msg-8693a023e292`
- Source: `message:msg-reply-546f215e9e35ab9b-reply`
- Source: `message:msg-reply-26b75b74e8f69ff7-reply`
- Source: `message:msg-reply-ae99571e2ee1b7a3-reply`
- Source: `message:msg-reply-0c9cb0695a41ca70-reply`
- Source: `message:msg-reply-b21b7235a597c92f-reply`
- Source: `context_pack:ctx-b3a4103ebb0eb679`
- Source: `question_ledger_digest:e334d31bdd276d0da6cca219accfe7cf4d44a7e0f02c8baca5880d1b68c0e6cc`
- Source: `event:evt-74da4e2bd33f`
- Source: `channel:ch-prd-clarification-2621451543/main`

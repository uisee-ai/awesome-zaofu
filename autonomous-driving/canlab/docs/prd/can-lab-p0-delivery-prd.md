# CAN Lab P0 可交付收口 PRD（Revision 6）

## Source Requirement
请对 CAN Lab 当前 P0 收口进行真实多视角评审。五个角色先独立盲审当前代码、README、测试和运行态，再进行交叉审阅与综合。重点核实：运行入口是否真实可用；核心实验流程是否闭环；样例数据与证据是否可复现；安全边界是否明确；剩余 P0 缺口如何拆分。最终只形成一份可执行 PRD 草案，包含目标、非目标、事实证据、验收标准、风险与最小任务切片。Owner 明确确认前，不得创建 Task，不得触发 Workflow。

## Requirement
CAN Lab P0 提供仅使用合成与离线数据的 DBC 浏览、确定性 CAN 回放、可追溯解码和虚拟仪表。资产身份按实际字节校验并在漂移时 fail closed；未知帧完整保留原始元数据且不伪造解码链；被动边界由版本化双向清单、负向 fixtures、六类零持久化断言和实际 HTTP CSP 响应头共同约束。交付证据绑定最终 main 提交、latest-stable Chromium 身份及不可变发布凭据，发布写入与复验权限分离。

## Decisions
- {"decision":"产品行为维持 AC-01 至 AC-17；动态浏览器资格、plan-port 和证据生产者边界属于独立交付控制。","id":"DEC-01","source_ref":"evt-238ab60cc604"}
- {"decision":"干净 checkout 的 main 提交是唯一 P0 发布真相。","id":"DEC-02","source_ref":"evt-6c35f677fdc0"}
- {"decision":"DBC、NDJSON 和 validation vectors 必须按实际字节计算 SHA-256，不一致即拒绝启动。","id":"DEC-03","source_ref":"evt-3c0d3111ce7d"}
- {"decision":"保留 latest-stable desktop Chromium 交付门禁并绑定实际可执行文件身份。","id":"DEC-04","source_ref":"evt-f7c292b8a2b5"}
- {"decision":"提交绑定的耐久证据包是发布阻断条件。","id":"DEC-05","source_ref":"evt-123c06cb4778"}
- {"decision":"未知帧必须展示完整原始元数据且不得产生 signal、formula 或 display chain。","id":"DEC-06","source_ref":"evt-48b7f5e3f81b"}
- {"decision":"被动边界必须以版本化 API/URL 清单、八类逐项负向 fixtures 和六类零持久化断言证明。","id":"DEC-07","source_ref":"evt-c4b5a4d92ac2"}
- {"decision":"最终 preview 必须通过 HTTP 响应头交付版本化 CSP，并以真实 CSP violation 和零到达证据证明阻断。","id":"DEC-08","source_ref":"evt-8454007f8e88"}
- {"decision":"只有 CAS 快进至 main 并对最终提交完整重验后才能收口。","id":"DEC-09","source_ref":"evt-7b830a308553"}
- {"decision":"CAS writer 与 verifier 权限分离；验证脚本不得更新 main。","id":"DEC-10","source_ref":"evt-908b21a55e06"}
- P0 是否接受将提交绑定的耐久证据包设为发布阻断条件？: 阻断式证据包
- Owner 是否确认产品 P0 仍以 AC-01 至 AC-17 为准，并将 plan-port、动态 latest-stable Chromium qualification 等要求作为独立交付控制而非产品需求？: 产品与交付分层
- Owner 是否要求浏览器按实际字节重算 DBC、NDJSON 与 validation vectors 的 SHA-256，不一致时 fail closed？: 运行时校验
- Owner 是否确认只有经 compare-and-swap 快进至 main、并对最终目标提交重验后，才能宣布 P0 收口？: CAS 快进重验
- P0 的规范交付目标是否必须是可从干净 checkout 直接运行和验收的 main 提交？: 干净 main 提交
- Owner 是否维持既有 D-11 的 latest-stable desktop Chromium 验收要求？: 维持最新稳定版
- 是否将 P0-CLOSE-04 及其浏览器断言明确为：未知帧必须逐项保留并展示 frameSeq、timestamp_us、CAN ID、isExtended/帧格式、DLC、raw bytes 和未解码原因，同时不得生成 signal、formula 或 display chain？: 是。P0-CLOSE-04 及浏览器断言必须明确要求未知帧逐项保留并展示 frameSeq、timestamp_us、CAN ID、isExtended/帧格式、DLC、raw bytes 和未解码原因，同时不得生成 signal、formula 或 display chain。
- 是否将 main 的 CAS 晋级拆为由 Owner 单独授权、token-gated 的 kernel/control-plane mutation action并生成不可变 CAS receipt，同时将 verify 限为只读消费该 receipt 后在最终 main 干净检出上复验，禁止 verify 角色或 tools/verify-p0-release.sh 直接更新 main？: 是。main 的 CAS 晋级必须由 Owner 单独授权、通过 token-gated kernel/control-plane mutation action 执行并生成不可变 CAS receipt；verify 角色和 tools/verify-p0-release.sh 只能只读消费该 receipt，并在最终 main 干净检出上复验，禁止直接更新 main。
- 是否将 P0-CLOSE-06、P0-CLOSE-08 及对应静态/浏览器验收明确为：维护允许与禁止的 API/URL 清单，以逐项负向 fixtures 证明 WebHID、WebBluetooth、WebSocket、EventSource、WebRTC、ServiceWorker、硬件及发送入口会使门禁失败，并在刷新前后断言 cookies、service-worker registrations 及既有四类存储均为空？: 采纳。P0-CLOSE-06、P0-CLOSE-08 及 V-P0-STATIC/V-P0-BROWSER 必须维护允许与禁止的 API/URL 清单；为 WebHID、WebBluetooth、WebSocket、EventSource、WebRTC、ServiceWorker、硬件访问与 CAN 发送入口逐项提供负向 fixture，并证明每一项都会使对应门禁失败。真实浏览器验收必须在刷新前后断言 cookies、service-worker registrations、localStorage、sessionStorage、IndexedDB 与 Cache Storage 全部为空；任何缺项均不得签收。
- 是否将 P0-CLOSE-06 与 V-P0-BROWSER 明确为：最终 main 的实际 loopback preview 必须通过 HTTP 响应头交付版本化 CSP，浏览器门禁须校验响应头并证明禁止连接由 CSP 本身阻断；仅有 meta CSP、未生效的 public/_headers 或依赖 Playwright 路由拦截均不得通过？: 采纳。P0-CLOSE-06 与 V-P0-BROWSER 必须要求最终 main 的实际 loopback preview 通过 HTTP 响应头交付版本化 CSP；浏览器门禁须读取并校验该响应头，并以真实 CSP violation/阻断证据证明禁止连接无法建立。仅有 meta CSP、未被实际 preview 应用的 public/_headers，或只依赖 Playwright route 拦截均不得通过；route 只能用于观测和采证，不能充当安全控制。

## Assumptions
- candidate/TASK-B064CA@f585111 继续作为增量实现基线，不重写已成立的领域核心。
- 受控 qualification 阶段允许访问官方 Stable 资格源；固定资格后浏览器验收可在无外网容器中运行。
- 产品运行期继续只消费仓库内合成或离线资产。

## Out of Scope
- 新增非 P0 产品功能。
- 真实 CAN 硬件接入、报文发送或车辆控制。
- 从讨论频道直接创建 Task、启动 Workflow 或修改 main。
- 以 candidate worktree、meta CSP 或运行态临时文件替代正式交付。

## Acceptance Criteria
- {"description":"最终 main 可从干净 checkout 直接完成安装、构建并以 loopback preview 启动。","evidence_method":{"artifacts":["artifacts/verification/p0/release/clean-checkout.json"],"verification_ids":["V-P0-RELEASE"]},"id":"P0-CLOSE-01","mandatory":true}
- {"description":"AC-01 至 AC-17 的 DBC 浏览、回放、解码、追踪和仪表黄金链全部通过。","evidence_method":{"artifacts":["artifacts/verification/p0/static/tests.json","artifacts/verification/p0/browser/trace.zip"],"verification_ids":["V-P0-STATIC","V-P0-BROWSER"]},"id":"P0-CLOSE-02","mandatory":true}
- {"description":"应用按实际字节重算 DBC、NDJSON 与 vectors 摘要；摘要、版本或身份不符时 fail closed，trace 绑定实际 log 与 DBC digest。","evidence_method":{"artifacts":["artifacts/verification/p0/static/assets.json","artifacts/verification/p0/browser/fail-closed.json"],"verification_ids":["V-P0-STATIC","V-P0-BROWSER"]},"id":"P0-CLOSE-03","mandatory":true}
- {"description":"未知帧逐项保留并展示 frameSeq、timestamp_us、CAN ID、isExtended/帧格式、DLC、raw bytes 和未解码原因，且无 signal、formula 或 display chain。","evidence_method":{"artifacts":["artifacts/verification/p0/static/unknown-frame.json","artifacts/verification/p0/browser/unknown-frame.png"],"verification_ids":["V-P0-STATIC","V-P0-BROWSER"]},"id":"P0-CLOSE-04","mandatory":true}
- {"description":"相同资产与控制序列产生一致的回放顺序、时间游标、解码结果和 trace identity。","evidence_method":{"artifacts":["artifacts/verification/p0/static/determinism.json"],"verification_ids":["V-P0-STATIC","V-P0-BROWSER"]},"id":"P0-CLOSE-05","mandatory":true}
- {"description":"版本化策略明确允许与禁止的 API/URL；WebHID、WebBluetooth、WebSocket、EventSource、WebRTC、ServiceWorker、硬件访问和 CAN 发送入口的逐项负向 fixture 均使门禁失败。实际 loopback preview 必须返回与策略一致的 Content-Security-Policy 响应头；对第二 loopback origin 的禁止连接必须产生 securitypolicyviolation 且 sentinel 零到达。Playwright route 只能观测并继续请求，不得 abort 或代替 CSP。","evidence_method":{"artifacts":["artifacts/verification/p0/static/boundary-matrix.json","artifacts/verification/p0/static/csp.json","artifacts/verification/p0/browser/csp-evidence.json"],"verification_ids":["V-P0-STATIC","V-P0-BROWSER"]},"id":"P0-CLOSE-06","mandatory":true}
- {"description":"在 1440x1000 viewport 中以真实指针和键盘完成黄金旅程，并生成成功截图与 trace。","evidence_method":{"artifacts":["artifacts/verification/p0/browser/golden-journey.png","artifacts/verification/p0/browser/trace.zip"],"verification_ids":["V-P0-BROWSER"]},"id":"P0-CLOSE-07","mandatory":true}
- {"description":"网络仅出现策略允许的 loopback 请求；刷新前后 cookies、service-worker registrations、localStorage、sessionStorage、IndexedDB 和 Cache Storage 全部为空。","evidence_method":{"artifacts":["artifacts/verification/p0/browser/network.json","artifacts/verification/p0/browser/storage.json"],"verification_ids":["V-P0-BROWSER"]},"id":"P0-CLOSE-08","mandatory":true}
- {"description":"实际浏览器满足执行时 latest-stable desktop Chromium，并绑定资格快照、executable path、version、SHA-256、镜像摘要和目标提交。","evidence_method":{"artifacts":["artifacts/verification/p0/browser/qualification.json"],"verification_ids":["V-P0-QUALIFY","V-P0-BROWSER"]},"id":"P0-CLOSE-09","mandatory":true}
- {"description":"耐久证据包绑定最终 commit/tree、资产摘要、浏览器资格、完整门禁输出、trace、截图、网络、存储、CSP、负向 fixture 矩阵、CAS receipt 及每个产物摘要。","evidence_method":{"artifacts":["artifacts/verification/p0/manifest.json"],"verification_ids":["V-P0-STATIC","V-P0-QUALIFY","V-P0-BROWSER","V-P0-RELEASE"]},"id":"P0-CLOSE-10","mandatory":true}
- {"description":"main 的 CAS 晋级仅由 Owner 单独授权的 token-gated kernel/control-plane mutation action 执行并产生不可变 receipt；verify 与仓库验证脚本无更新 main 的能力。","evidence_method":{"artifacts":["artifacts/verification/p0/release/cas-receipt.json","artifacts/verification/p0/release/writer-separation.json"],"verification_ids":["V-P0-STATIC","V-P0-RELEASE"]},"id":"P0-CLOSE-11","mandatory":true}
- {"description":"只读 verifier 消费 CAS receipt，在最终 main 干净检出上重跑完整门禁，并确认发布身份与 canonical runtime projection 无完成/未交付矛盾。","evidence_method":{"artifacts":["artifacts/verification/p0/release/final-verification.json","artifacts/verification/p0/release/runtime-audit.json"],"verification_ids":["V-P0-RELEASE"]},"id":"P0-CLOSE-12","mandatory":true}

## Verification Commands
- `{"acceptance_ids":["P0-CLOSE-02","P0-CLOSE-03","P0-CLOSE-04","P0-CLOSE-05","P0-CLOSE-06","P0-CLOSE-10","P0-CLOSE-11"],"command":"npm ci && npm run lint && npm test && npm run build && node tools/verify-assets.mjs --output artifacts/verification/p0/static/assets.json && node tools/check-passive-boundary.mjs --policy config/passive-boundary-policy.json --fixtures tests/fixtures/passive-boundary --output artifacts/verification/p0/static/boundary-matrix.json && node tools/check-csp-delivery.mjs --policy config/csp-policy.json --server tools/serve-p0-preview.mjs --output artifacts/verification/p0/static/csp.json","deterministic":true,"id":"V-P0-STATIC","owner":"impl","producer_paths":["config/passive-boundary-policy.json","config/csp-policy.json","tools/verify-assets.mjs","tools/check-passive-boundary.mjs","tools/check-csp-delivery.mjs","tools/serve-p0-preview.mjs","tests/fixtures/passive-boundary","artifacts/verification/p0/static"],"reusable":true,"tier":"static","timeout_seconds":900}`
- `{"acceptance_ids":["P0-CLOSE-09","P0-CLOSE-10"],"command":"./tools/qualify-stable-chromium.sh --channel stable --platform linux64 --output artifacts/verification/p0/browser/qualification.json","deterministic":false,"id":"V-P0-QUALIFY","owner":"verify","producer_paths":["tools/qualify-stable-chromium.sh","tools/browser/Dockerfile.p0","artifacts/verification/p0/browser/qualification.json"],"reusable":true,"tier":"runtime","timeout_seconds":1800}`
- `{"acceptance_ids":["P0-CLOSE-02","P0-CLOSE-03","P0-CLOSE-04","P0-CLOSE-05","P0-CLOSE-06","P0-CLOSE-07","P0-CLOSE-08","P0-CLOSE-09","P0-CLOSE-10"],"command":"docker run --rm --network=none --read-only --user \"$(id -u):$(id -g)\" --tmpfs /tmp:rw,nosuid,nodev,size=512m -e P0_EVIDENCE_DIR=/evidence/browser -e P0_QUALIFICATION_RECEIPT=/evidence/browser/qualification.json -v \"$PWD/artifacts/verification/p0:/evidence\" canlab-p0-chromium:qualified npx --no-install playwright test tests/e2e/p0-closeout.spec.ts --config=playwright.p0.config.ts --project=chromium","deterministic":true,"id":"V-P0-BROWSER","owner":"verify","producer_paths":["playwright.p0.config.ts","tests/e2e/p0-closeout.spec.ts","config/passive-boundary-policy.json","config/csp-policy.json","tools/serve-p0-preview.mjs","tools/browser/Dockerfile.p0","artifacts/verification/p0/browser"],"reusable":true,"tier":"e2e","timeout_seconds":900}`
- `{"acceptance_ids":["P0-CLOSE-01","P0-CLOSE-02","P0-CLOSE-03","P0-CLOSE-04","P0-CLOSE-05","P0-CLOSE-06","P0-CLOSE-07","P0-CLOSE-08","P0-CLOSE-09","P0-CLOSE-10","P0-CLOSE-11","P0-CLOSE-12"],"command":"./tools/verify-p0-release.sh --mode read-only --expected-old-main 2583d6e47ec4c890fa63b9f81b80f07e5c2586ef --candidate-manifest artifacts/verification/p0/release-candidate.json --cas-receipt artifacts/verification/p0/release/cas-receipt.json --output artifacts/verification/p0/release","deterministic":true,"id":"V-P0-RELEASE","owner":"verify","producer_paths":["tools/verify-p0-release.sh","artifacts/verification/p0/release-candidate.json","artifacts/verification/p0/release/cas-receipt.json","artifacts/verification/p0/release"],"reusable":true,"tier":"runtime","timeout_seconds":2400}`

## Risks
- {"id":"R-01","mitigation":"仅接受 CAS receipt 与最终 main 干净检出证据。","risk":"候选实现未进入 main，候选完成仍可能被误报为正式交付。"}
- {"id":"R-02","mitigation":"运行时重算全部资产摘要并 fail closed。","risk":"metadata 与实际资产字节漂移会产生错误但稳定的 trace identity。"}
- {"id":"R-03","mitigation":"静态与浏览器测试逐项断言完整原始元数据。","risk":"未知帧字段不完整会掩盖 D-07 缺口。"}
- {"id":"R-04","mitigation":"版本化双向清单、八类负向 fixtures 和六类浏览器零状态断言。","risk":"静态扫描遗漏禁用 API、URL 或持久化表面会造成假阴性。"}
- {"id":"R-05","mitigation":"验证真实响应头、securitypolicyviolation、sentinel 零到达，并禁止 route.abort。","risk":"meta CSP、未生效的 public/_headers 或 route.abort 会造成 CSP 已生效的假象。"}
- {"id":"R-06","mitigation":"受控 latest-stable qualification 和提交绑定耐久证据包。","risk":"浏览器资格过期或证据未绑定最终提交。"}
- {"id":"R-07","mitigation":"独立 token-gated writer、只读 verifier 与最终 runtime audit。","risk":"验证者修改验收对象或运行态投影继续矛盾。"}

## Dissent
- {"id":"DISSENT-01","issue":"latest-stable Chromium 属于产品要求还是交付控制。","resolution":"保留门禁并归入交付控制。","status":"resolved_by_owner"}
- {"id":"DISSENT-02","issue":"未知帧验收未枚举完整元数据。","resolution":"已逐项冻结字段和禁止伪造链。","status":"resolved_by_owner"}
- {"id":"DISSENT-03","issue":"CAS writer 与 verifier 权限混同。","resolution":"已拆分为独立控制面动作和只读复验。","status":"resolved_by_owner"}
- {"id":"DISSENT-04","issue":"被动边界和存储验收不可证伪。","resolution":"已增加双向清单、逐项负向 fixtures 与六类零状态断言。","status":"resolved_by_owner"}
- {"id":"DISSENT-05","issue":"meta CSP、未生效 headers 或 route 拦截可能冒充实际 CSP 交付。","resolution":"已要求真实响应头、CSP violation 和 sentinel 零到达证据。","status":"resolved_by_owner_pending_artifact_review"}

## Open Questions
- None.

## Recommended Workflow
```json
{
  "abort_conditions": [
    "main 或候选身份与批准清单不符。",
    "任一资产摘要、浏览器资格或证据摘要不匹配。",
    "任一禁用 fixture 未使门禁失败。",
    "实际 preview 缺少或错误返回 CSP 响应头。",
    "禁止连接未产生真实 CSP violation、到达 sentinel，或使用 route.abort 充当控制。",
    "任一持久化表面未检查或非空。",
    "verify 或仓库脚本尝试更新 main。"
  ],
  "control_actions": [
    {
      "authorized_by": "owner",
      "forbidden_callers": [
        "verify",
        "tools/verify-p0-release.sh"
      ],
      "id": "ACTION-CAS-01",
      "input": "已验证候选身份及 expected-old-main",
      "output": "不可变 CAS receipt",
      "type": "token_gated_kernel_mutation"
    }
  ],
  "invoke_now": false,
  "kind": "controlled_prd_dag",
  "preconditions": [
    "product_pm、arch、critic、security_reviewer 对 Revision 6 的同一 artifact digest 完成签收。",
    "Owner 对最终 Revision 6 作整体确认并另行授权创建 Task 与启动 Workflow。",
    "main 基线和候选身份未发生未审计漂移。"
  ],
  "requires_gate": true,
  "sequence": [
    "并行实现并验证 SLICE-01 至 SLICE-03。",
    "实现 SLICE-04 并对候选执行只读完整验证。",
    "经单独授权执行 ACTION-CAS-01。",
    "只读 verifier 在最终 main 干净检出上执行 V-P0-RELEASE。"
  ],
  "task_slices": [
    {
      "acceptance_ids": [
        "P0-CLOSE-02",
        "P0-CLOSE-03",
        "P0-CLOSE-04",
        "P0-CLOSE-05"
      ],
      "id": "SLICE-01",
      "title": "资产、trace 与未知帧完整性"
    },
    {
      "acceptance_ids": [
        "P0-CLOSE-06",
        "P0-CLOSE-07",
        "P0-CLOSE-08"
      ],
      "id": "SLICE-02",
      "title": "可证伪被动边界、实际 CSP preview 与浏览器闭环"
    },
    {
      "acceptance_ids": [
        "P0-CLOSE-09",
        "P0-CLOSE-10"
      ],
      "id": "SLICE-03",
      "title": "latest-stable 资格与耐久证据包"
    },
    {
      "acceptance_ids": [
        "P0-CLOSE-01",
        "P0-CLOSE-11",
        "P0-CLOSE-12"
      ],
      "id": "SLICE-04",
      "title": "只读发布验证器与运行态对账"
    }
  ]
}
```

## Provenance
- Channel: `ch-canlab-prd-multilens-v2-20260808`
- Thread: `main`
- Source: `event:evt-8454007f8e88`
- Source: `event:evt-00e4a7422631`
- Source: `event:evt-f2e3aca05df7`
- Source: `event:evt-cf57676a0ae4`
- Source: `event:evt-ca384c09b133`
- Source: `event:evt-5d4591cffad4`
- Source: `event:evt-990da65eee24`
- Source: `event:evt-c83e76e4f7f1`
- Source: `event:evt-3c447bf08465`
- Source: `event:evt-3a1bbcc56ca4`
- Source: `event:evt-6a44ea676722`
- Source: `context_pack:ctx-46124bb898ed59bb`
- Source: `context_pack_sha256:be61ccb775bbb6e4be994c167f5c0ecd9cbde5f2d8567a15f8601834f46d4b51`
- Source: `question_ledger_digest:533ad1979d3c9bfbb6587cefc04826bb0d40eb10de3c1c7f1701bd4a909dddfe`
- Source: `evt-30c5bf9f2db0`
- Source: `evt-a17b9194a4e5`
- Source: `evt-108ded7db2d3`
- Source: `evt-00e4a7422631`
- Source: `evt-ca384c09b133`
- Source: `evt-990da65eee24`
- Source: `evt-8454007f8e88`
- Source: `event:evt-11defbe40307`
- Source: `channel:ch-canlab-prd-multilens-v2-20260808/main`

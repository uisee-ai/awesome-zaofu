# HighwayPilot Lab v7 PRD 验收回填（实施快照）

更新时间：2026-08-27（Asia/Shanghai）
Git：`d55e6d686b6b0143db795ec03cdfbe74ae190b94`（工作树仍有本轮实施改动，未创建新提交）
环境：Linux x86_64、Python 3.11、`.venv`、Node 22、Chrome/Playwright、WebGL2。
锁文件：`package-lock.json` sha256 `4226486f2b8ac4c8cef9c4115a1af42551f96b0ec95d2cf7ca55420bf5b7d0b2`；`uv.lock` sha256 `700bfa1669e516e85bf1de897e096d9cd6962a0fe5726de500a78aea3a66db95`。

## 本轮范围裁决（2026-08-28）

Owner 已明确将以下两项延期，本轮不实施，也不得因为已有脚手架、模型文件或零散说明而推定通过：

- **完整开源交付文档和录屏**：保持 `pending`；本轮不补 Quick Start、架构说明、训练指南或最终录屏。
- **可训练强化学习基线**：保持 `partial`；保留现有 ONNX 推理与训练脚手架，但本轮不重新训练、不调参、不签发学习策略质量通过结论。

Owner 已于 2026-08-28 确认并完成本轮范围：Gymnasium `construction-v0` 注册与标准接口、安全车道奖励、
`AC-F01` 背景交通/成功/碰撞/失败/超时验收闭环，以及基础策略比较指标的真实页面呈现。上述两项延期内容仍未实施。

## 证据命令

- `PYTHONPATH=src .venv/bin/python -m pytest -q`：退出码 0，178 passed。
- `PATH=.venv/bin:$PATH npm test`：退出码 0，19 passed。
- `npm run typecheck`：退出码 0。
- `npm run build` + `.venv/bin/python scripts/assemble-release.py`：退出码 0，真实入口产物 `dist/web/assets/index-BgaFFHX0.js`。
- `npx playwright test tests/e2e/assembly/product.spec.ts --reporter=line`：退出码 0，3 passed；包含新增安全车道奖励和四策略指标表真实入口验收。
- `zf validate --instructions`、`zf update agents-md --check`：退出码 0。

## 规范性 AC 状态

状态只使用 `passed`、`partial`、`pending`、`failed`；未达到最高要求的条目不推定通过。

| ID | 状态 | 当前实现/producer | 证据与未闭合项 |
|---|---|---|---|
| AC-F01 | passed | `simulation/gym_env.py`、`simulation/environment.py`、`simulation/authority.py` | `gym.make("construction-v0")`、env checker、成功、真实碰撞、超时及四预设社会车辆核心区参与均通过；施工障碍不再被提前的非物理 `missed_merge` 判定抢占。 |
| AC-F02 | passed | `rng/contract.py`、`simulation`、`strategies/policy.py` | 确定性与随机策略测试通过。 |
| AC-F03 | passed | `web/src/hmi/renderer/HighwayScene.ts`、`web/src/hmi/App.ts` | Playwright 真实入口 3 passed；Three.js Scene/Renderer/canvas/camera 已验证。 |
| AC-F04 | passed | `session/core.py`、`sessionControls.ts` | 播放/暂停/单步/人工动作/四档倍速 focused tests 通过；需补逐档实时因子原始测量。 |
| AC-F05 | partial | `config/parser.py`、`App.ts`、`server.py` | Schema、字段表单、预览校验、摘要已接通；奖励/施工字段真实浏览器逐字段证据仍待补。 |
| AC-F06 | partial | `strategies/policy.py`、`comparison.py`、`server.py`、`comparisonPresenter.ts`、`App.ts` | 同配置同 Seed 的四策略表已展示奖励、碰撞/成功/超时、均速、耗时、换道、TTC、舒适度和版本，失败 Episode 可保存；学习基线质量按 Owner 裁决延期，因此保持 partial。 |
| AC-F07 | passed | `episodes/library.py`、`api/server.py`、`ApiClient.ts` | Library API、保存/列表/详情/导入/导出/删除及配额测试通过；需补服务重启后浏览器级证据。 |
| AC-F08 | partial | `session/core.py`、`ApiClient.ts` | 两阶段 Resume 和旧凭证失效测试通过；真实浏览器断线 59/60 秒边界原始证据待补。 |
| AC-F09 | partial | `HighwayScene.ts`、session cleanup loop | resize/context lost/restored/dispose 已实现；20 次实时↔回放资源曲线和 GPU soak 尚未采集。 |
| AC-F10 | passed | `scripts/start-demo.sh`、release assembly | 真实启动、健康检查、生产构建和 Playwright smoke 通过；正式发布上传仍受性能门阻断。 |
| AC-N01 | passed | `SessionControls.ts`、`App.ts` | 未连接/无会话控件禁用，单元与真实 smoke 通过。 |
| AC-N02 | partial | `config/parser.py`、`/api/config/validate` | Seed/未知字段/组合约束后端拒绝已测试；字段级浏览器错误提示仍待补。 |
| AC-N03 | partial | `api/static.py`、`HighwayScene.ts` | MIME/路径穿越和 WebGL 降级测试通过；context lost 真实浏览器证据待补。 |
| AC-N04 | passed | `SessionRegistry`、Project Episode Library API | 会话隔离、正式 Library 边界和错误隐藏测试通过。 |
| AC-N05 | partial | `session/core.py` | 并发双恢复、序列/幂等测试通过；真实 59/60 秒浏览器证据待补。 |
| AC-N06 | passed | `Session.expired`、shutdown cleanup | 超时/显式关闭/服务 shutdown 失效路径测试通过。 |
| AC-N07 | passed | `RuntimeService` startup cleanup loop | 断线/空闲/最长生命周期扫描链路已调度并通过 session 测试。 |
| AC-N08 | pending | `HighwayScene.dispose`、ReplayController | 资源释放代码已实现；长时间浏览器曲线尚未测量。 |
| AC-N09 | partial | `ProjectEpisodeLibrary` | 持久化格式与 hash/metadata 已通过；需服务重启后真实 API 回归证据。 |
| AC-N10 | partial | `Session._episode_recorder`、cleanup | 临时记录与生命周期清理已接通；需补清理前后 Library 列表原始证据。 |
| AC-N11 | passed | `episodes/library.py` | 单文件/总容量/数量/并发原子拒绝测试通过。 |
| AC-N12 | passed | replay parser/import transport | 损坏、未知版本、gzip 膨胀、路径与符号链接边界测试通过。 |
| AC-N13 | passed | `model/runtime.py` | ONNX 白名单、hash、算子、provider、资源门测试通过。 |
| AC-N14 | passed | `security/loopback.py`、entrypoint | Host/Origin/DNS rebinding/非 loopback 拒绝及动态端口 smoke 通过。 |
| AC-N15 | passed | `start-demo.sh`、FastAPI shutdown | 正常停止清理本实例并释放会话；发布 verifier 退出码 0。 |

## 强制子验收

`AC-F03-AUTHORITY`、`AC-F09-RENDERER`、`AC-F09-REPLAY`、`AC-F09-SESSION`、`AC-SEC-TOKEN`、`AC-UI-CLEAN`、`AC-BUILD` 已有代码或 focused evidence；`AC-F05-UI`、`AC-F06-RULE`、`AC-F06-EXPLAIN`、`AC-N03-WEBGL`、`AC-VIS-EVIDENCE` 仍标记 `partial/pending`，原因与上表一致。性能 Owner 阈值尚未冻结，因此 release verifier 当前明确返回 `upload_authorized: false` 和 `OWNER_PERFORMANCE_BUDGET_NOT_FROZEN`。

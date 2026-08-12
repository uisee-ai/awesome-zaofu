# Alpamayo Studio 应用

## 当前能力

- Next.js 16 + React 19 研究工作台，支持桌面和移动端。
- FastAPI + Pydantic API，输入与模型结果执行 schema 校验。
- 一个全局 FIFO/lease worker，通过 `runType` 和 `demoId` 确定性路由。
- 不可变 SceneVersion、运行记录、刷新恢复和人工审核记录。
- VQA、Chain of Causation、Meta Action、标签和 64 点/6.4 秒 BEV 轨迹。
- Scene Workbench、Navigation、Camera Ablation、Scene VQA、Auto Label、Regression & Judge 六个入口。
- Provider 原始响应仅写入权限为 `0600` 的本地 sidecar，公共 API 返回结构化结果、digest 和引用。

## 当前交付边界

本地产品主路径使用仓库内可审计的四摄像头 Golden Scene，六个 Demo 都通过同一个 SceneVersion、队列和结果合同执行。图片上传 API 已具备 MIME、扩展名、签名和大小校验，但 Web 端的任意多文件场景编辑器尚未接入该主路径。

Navigation、Camera Ablation、Auto Label 和 Regression 已可从统一界面提交模式参数并保存独立结果；多分支轨迹叠加、批量评测集执行和完整回归报告仍由现有领域模块承载，尚未接入本地 FastAPI 主应用。当前 `/api/experiments`、`/api/evaluation-sets` 和 `/api/evaluation-runs` 仅提供创建接口骨架，不应视为完整 P1 批处理闭环。

## 目录

```text
src/app/                 Next.js 页面与样式
src/lib/                 Web API client
web/src/features/        可复用轨迹、导航、消融、标注领域模块
packages/contracts/      TypeScript canonical scene/result contract
backend/studio/app/      FastAPI、provider adapter、queue 与 persistence
tests/                   Node/Python/Playwright 验证
deploy/                  本地运行、Docker 和浏览器验收脚本
```

## 环境

- Node.js 20.9+，推荐 Node.js 24。
- Python 3.11+。
- Docker，仅用于容器化运行或 Playwright 浏览器验收。

```bash
npm install
python -m venv .venv
.venv/bin/pip install -e backend
source .venv/bin/activate
```

## 启动

确定性本地模式：

```bash
ALPAMAYO_STUDIO_PROVIDER_MODE=mock \
  bash deploy/scripts/run-local-studio.sh
```

Web 默认监听 `http://localhost:3000`，API 默认监听 `http://localhost:8000`。

真实 LiteLLM：

```bash
export ALPAMAYO_STUDIO_PROVIDER_MODE=litellm
export LITELLM_BASE_URL=http://your-litellm-host
export LITELLM_API_KEY=your-key
export LITELLM_MODEL_NAME=alpamayo-vqa
bash deploy/scripts/run-local-studio.sh
```

Provider 必须返回满足 canonical result contract 的 JSON：非空 VQA、CoC、Meta Action，以及从 `0.1` 到 `6.4` 秒的 64 个 `position[3] + rotation[3][3]` 轨迹点。不完整结果会明确失败，不会伪造成成功。

Docker Compose：

```bash
docker compose -f deploy/local/docker-compose.yml up --build
```

## 验证

```bash
npm run lint
npm test
npm run test:backend
npm run build
```

启动本地服务后，使用仓库规定的 Docker Playwright 环境执行真实产品门禁：

```bash
ALPAMAYO_STUDIO_URL=http://127.0.0.1:3000 \
  npm run test:e2e:docker
```

该门禁会真实创建 Scene、依次运行六个 Demo，并验证：

- 四路 Camera 图片已加载且具有非零像素尺寸。
- 六个 Demo 产生各自的 provider operation/result identity。
- VQA、CoC、Meta Action 和 64 点轨迹可见。
- 刷新后结果可恢复。
- 桌面与移动端无页面级横向溢出，并生成截图证据。

## 本地状态

默认运行数据写入 `app/data/`：

```text
data/studio-state.json
data/assets/
data/provider-responses/
```

这些文件是本地运行状态，不进入 Git。当前单用户本地版本使用原子 JSON store；生产部署可在保持 API/Repository 边界不变的前提下替换为 PostgreSQL。Redis 不是本地单并发模式的前置条件。

Alpamayo Studio 仅用于研究、实验、评测与演示。模型输出不能直接用于真实车辆控制，也不构成经过验证的驾驶安全结论。

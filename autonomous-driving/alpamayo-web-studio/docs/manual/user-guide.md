# Alpamayo Web Studio 使用教程

Alpamayo Web Studio 是面向自动驾驶研究和评测的本地场景推理工作台。当前公开快照
默认使用确定性 mock provider，可在不配置外部模型和密钥的情况下体验完整产品主路径。

> 安全边界：模型输出只用于研究、评测和演示，不得直接用于真实车辆控制，也不构成
> 驾驶安全结论。

## 1. 安装并启动

在项目目录执行：

```bash
cd autonomous-driving/alpamayo-web-studio/app
npm install
python -m venv .venv
.venv/bin/pip install -e backend
ALPAMAYO_STUDIO_PROVIDER_MODE=mock bash deploy/scripts/run-local-studio.sh
```

打开 <http://localhost:3000>。Web 会通过本地 FastAPI 服务访问场景、队列和结果；
默认 API 地址为 <http://localhost:8000>。

## 2. 创建共享场景

1. 点击页面左侧的创建场景命令。
2. 输入场景名称，生成不可变 `SceneVersion`。
3. 在左侧场景列表中确认新场景已被选中。

当前主路径使用仓库内置的四摄像头 Golden Scene。六个 Demo 共享同一个
`SceneVersion`，切换 Demo 不会重复上传或复制场景。

## 3. 运行六个 Demo

左侧导航提供六个入口：

| Demo | 主要用途 |
| --- | --- |
| Scene Workbench | 查看共享场景、推理结果和轨迹摘要 |
| Navigation Lab | 输入导航指令并检查对应推理结果 |
| Camera Ablation | 比较完整相机输入与消融条件 |
| Scene VQA | 对道路场景执行视觉问答 |
| Auto Label Studio | 查看标签并记录人工接受或拒绝 |
| Regression & Judge | 检查候选运行的回归判断信息 |

选择一个 Demo 后点击 **Run inference**。运行依次进入 `queued`、`running` 和终态；
本地模式只有一个全局 worker，因此多个请求按 FIFO 顺序执行。

## 4. 阅读结果

成功结果至少包含：

- VQA 文本；
- Chain of Causation；
- Meta Action；
- 未来 6.4 秒的 64 点轨迹；
- Provider、运行 ID、SceneVersion ID 和响应摘要。

页面右侧展示当前结果，左侧历史区可以切换之前的运行。刷新页面后，已持久化的场景
和运行记录会从 `app/data/` 恢复。

## 5. 人工审核

在 **Auto Label Studio** 中选择已完成运行后，可以记录接受或拒绝。审核决定和标签
与对应运行绑定，不会修改不可变的 SceneVersion。

## 6. 使用真实 LiteLLM Provider

只有在 Provider 能返回 canonical result contract 时才启用真实模式：

```bash
export ALPAMAYO_STUDIO_PROVIDER_MODE=litellm
export LITELLM_BASE_URL=http://your-litellm-host
export LITELLM_API_KEY=your-key
export LITELLM_MODEL_NAME=alpamayo-vqa
bash deploy/scripts/run-local-studio.sh
```

不完整或不符合 schema 的 Provider 响应会明确失败，不会伪造成成功。密钥只通过环境
变量提供，不应写入源码、截图或 Git。

## 7. 验证当前快照

```bash
npm run lint
npm test
npm run test:backend
npm run build
```

真实浏览器门禁使用仓库提供的 Docker 脚本：

```bash
ALPAMAYO_STUDIO_URL=http://127.0.0.1:3000 npm run test:e2e:docker
```

该门禁会创建 Scene、依次运行六个 Demo，并验证相机图片、运行身份、VQA/CoC/
Meta Action、64 点轨迹、刷新恢复和桌面/移动端布局。

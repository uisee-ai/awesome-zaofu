# Troubleshooting

## 页面仍显示旧版资源

确认服务由当前项目根目录的 `scripts/start-demo.sh` 启动，并检查脚本是否重新执行了
`scripts/assemble-release.py`。浏览器可使用强制刷新，但不要把缓存现象当作源码版本证据。

## 会话无法启动

先检查配置是否符合 `schemas/construction-config/v1.schema.json`，再确认 `8000` 端口未被
占用。服务只接受 loopback 访问，非 `127.0.0.1` 地址不是受支持的部署方式。

## ONNX 策略没有结果

检查 `models/construction-dqn-v1/manifest.json` 与模型文件是否存在且 hash 合同匹配。
ONNX 推理合同存在不代表训练质量已完成验证；该范围在当前项目中仍是延期项。

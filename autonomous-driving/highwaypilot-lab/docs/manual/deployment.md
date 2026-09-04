# Deployment

HighwayPilot Lab 当前是本机单用户服务。`scripts/start-demo.sh` 和 Python 入口均要求
loopback host（`127.0.0.1`）；默认端口为 `8000`，可用 `HIGHWAYPILOT_PORT` 覆盖。

正式运行前先执行：

```bash
uv lock --check
npm run typecheck
npm run build
```

当前材料不宣称远程部署、多用户调度、生产级可用性或真实车辆安全认证。

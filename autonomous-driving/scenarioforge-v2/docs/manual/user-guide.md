# 用户手册

## 1. 打开工作台

启动命令：

```bash
uv run scenarioforge web --port 8000
```

浏览器进入 <http://127.0.0.1:8000/>。页面顶端的 Scenario Studio 把三种输入方式收在
同一个执行入口中。

## 2. 使用内置模板

1. 点击 `Built-in templates`。
2. 在下拉框选择场景；标签会说明它属于 MetaDrive 还是 SMARTS。
3. 阅读参与者、场景目的和后端信息。
4. 点击 `Run selected scenario`。
5. `Worker is running` 表示独立仿真进程仍在工作。第一次运行可能因后端初始化较慢。
6. 终态出现后，在 `Run evidence` 查看结果，再在 `Trajectory player` 播放轨迹。

MetaDrive 模板包括前车急刹、施工并道、危险切入、高速汇入和无保护左转。SMARTS 模板
包括高速汇入、竞争换道、横向闯红灯、行人红灯横穿和无保护左转。

## 3. 使用自然语言

1. 点击 `Natural language`。
2. 输入受支持的 benchmark intent，例如：

   ```text
   双车道高速公路上，自车以 100 km/h 跟随，前车突然急刹。
   ```

3. 点击 `Preview generated JSON`。
4. 检查系统生成的字段、默认值和缺失项。
5. 根据需要修改 JSON 或右侧表单，再执行 Adapter preflight。
6. 只有诊断通过后才确认一次运行。

离线 Provider 当前识别：前车急刹、行人/人行横道、横向闯红灯、无保护左转、竞争换道
和高速汇入。它不会理解任意自由文本，也不会调用云端大模型。

## 4. 使用严格 JSON

1. 点击 `JSON`。
2. 粘贴一个完整 JSON 对象；可从 `examples/p0c/` 或测试 fixture 开始修改。
3. 点击页面提供的校验/应用操作，先修复字段诊断。
4. 进行 Adapter preflight，确认能力映射和后端。
5. 点击确认运行。系统会把确认绑定到已校验 revision，修改内容后必须重新预检。

不要在 JSON 中放入密码、Token、文件命令或第三方可执行代码。服务会拒绝危险字段和越界
路径，但这不是上传秘密的理由。

## 5. 理解运行状态

- `starting/running`：Worker 正在初始化或推进仿真。
- `success`：运行完成，不等同于场景一定“安全”，仍要看目标结果与指标。
- `failed`：仿真或合同失败；查看错误码、事件和已发布证据。
- `timeout`：超过受控时间上限，Worker 被终止。

页面不会在运行结束前伪造轨迹。首次 SMARTS 启动通常比纯页面渲染慢。

## 6. 使用 3D 回放

1. 点击播放/暂停控制。
2. 拖动时间轴查看任意 tick。
3. 使用上一事件/下一事件跳转到关键时刻。
4. 观察图例区分 ego、受控 Agent、社会车辆和行人。
5. 跟车摄像机会随 ego 移动；道路、冲突区和信号灯用于解释轨迹，不代表照片级渲染。

必须结合 `Run evidence` 中的速度、碰撞、最小间距/TTC、事件顺序和终态理解回放，不要只
凭动画做安全结论。

## 7. 保存与复现

创作区支持 draft、不可变 revision、导入/导出、preflight 和 save-and-run。需要命令行
三次复现时使用：

```bash
uv run scenarioforge reproduce examples/p0a/brake_lead.json \
  --comparison-id my-check --run-id-prefix my-check-run
```

复现是重新运行固定策略并比较结果，不是把历史动作重新播放一遍。

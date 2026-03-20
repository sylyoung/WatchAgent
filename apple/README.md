# Apple Watch / iPhone 端集成说明

本目录提供可直接复制到 Xcode 工程的 Swift 源码骨架。

## 推荐工程结构
1. 推荐直接运行仓库脚本自动生成工程：`./scripts/generate_xcode_project.sh`。
2. 若手动创建：创建 iOS App，并勾选 Watch App Companion。
3. 将 `WatchAgentShared` 作为共享 group 添加到 iOS + watch targets。
4. 将 `WatchAgentWatchApp` 文件添加到 watch target。
5. 将 `PhoneBridgeApp` 文件添加到 iOS target。

## 能力和权限
- Watch 端：watchOS 系统听写面板（Dictation）+ 语音播报。
- Watch 端：`AppIntents/AppShortcuts` 支持 Siri 短语入口。
- iPhone 端：`WatchConnectivity`（默认 relay + 状态镜像）。
- 网络：允许访问后端地址（默认 `http://127.0.0.1:8787`）。

## 交互策略
- 不做持续后台唤醒词。
- 双入口：表盘点按启动 + Siri 短语启动。
- Codex 审批卡采用单卡串行：每次仅展示当前 1 条，处理后切换下一条。
- 卡片显示会话上下文与当前进度（x/y）。
- 进入 Codex 审批页后，隐藏通用”开始说话/快捷技能”，仅保留审批相关操作。
- Approve 绑定为主动作，可由 Double Tap 触发（保留按钮点击兜底）。
- 审批采用二段式二元决策：第一步 `Yes/No`，点 `No` 后第二步 `直接拒绝/语音补充`。
- 语音补充路径会拉起听写并回传 `followup_text`。
- 晨间Skill由主Agent快速首答，SubAgent增量汇报通过 events/stream 并入播报。


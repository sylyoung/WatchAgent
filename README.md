# WatchAgent — 腕上 AI 生活助理

语音驱动、主动感知、手腕确认——让 Apple Watch 成为真正能帮你把日子过好的 AI 代理。

## 架构

```
Apple Watch  ←→  iPhone Relay  ←→  Mac 后端 (localhost:8787)
  watchOS App      WatchConnectivity    Starlette + LLM Agent
  语音输入/输出     WCSession 中转       技能执行 / 工具调用
```

## 目录

| 目录 | 内容 |
|------|------|
| `apple/` | watchOS App + iPhone Relay（Swift） |
| `backend/` | Python 后端：Agent 编排、技能、工具、TTS |
| `contracts/` | JSON Schema 接口契约 |
| `scripts/` | 演示与辅助脚本 |
| `docs/` | 架构说明、API 文档、开发笔记 |

## 快速开始

**后端**

```bash
cd backend
cp .env.example .env   # 填入 API Key
pip install -r requirements.txt
python run_server.py   # 启动于 http://127.0.0.1:8787
```

**Watch App**

用 Xcode 打开 `WatchAgent.xcodeproj`，选择 Watch target，部署到设备。

## 六大技能

| 技能 | 触发词示例 | 工具 |
|------|-----------|------|
| 晨间简报 | "今日日程" | 天气、微信、待办、Codex 状态（并行） |
| 工作进展 | "工作进展" | Git 状态、Codex 任务、未读消息 |
| 查看快递 | "查看快递" | 淘宝 + 京东物流（并行） |
| 我的消息 | "我的消息" | 微信会话列表，可生成发送确认卡 |
| 健康管理 | "健康"、"睡眠" | HealthKit（运动/心率/睡眠/用药） |
| 出行叫车 | "叫车" | 生成叫车确认卡，手表 Double Tap 授权 |

## 环境变量

参见 `backend/.env.example`，需配置火山引擎 TTS 和豆包 LLM 的 API Key。

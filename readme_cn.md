# 🧠 Mimir (弥米尔)

> *"Mimir's head whispers the secrets of the Nine Realms to the All-Father, for even without a body, wisdom remains eternal."*

**Mimir** 是一款革命性的、纯 Python 实现的确定性“骨架记忆”系统。它为 AI 代理（如 Claude Code）提供了超轻量、长周期的上下文追踪与关系记忆能力，彻底舍弃了沉重的向量数据库与外部依赖。

---

## ⚖️ 核心哲学：Headless Wisdom (无身之智)

在北欧神话中，弥米尔虽然失去了身体，但他的头颅依然是宇宙间最伟大的智慧源泉。本项目承袭此意：
- **Headless (无数据库):** 无需 Qdrant, 无需 Ollama, 无需 SQLite。记忆即代码。
- **Deterministic (确定性):** 记忆不再是概率性的向量搜索，而是结构化的 Python 模块（Skeletons）。
- **Ageless (长效性):** 自动提取跨会话的决策、里程碑与关联，构建永不丢失的记忆网络。

## 🛠️ 核心功能

- **Pythonic Skeletons:** 对话记录被自动挖掘并转化为 `.mimir/skeleton/` 下的可执行 Python 模块，支持 AST 级检索。
- **Relationship Layer:** 自动链接不同会话中的相同话题、代码文件与关键决策，形成记忆骨架。
- **Zero-Latency Search:** 纯本地规则引擎，优先级排序算法确保秒级响应，告别向量检索的延迟与幻觉。
- **MCP Native:** 完美适配 Model Context Protocol，让你的 AI 能够随时通过 `mimir_status` 唤醒记忆。

## 🚀 快速开始

### 1. 安装
```bash
pip install -e .
```

### 2. 配置 MCP
将 Mimir 接入你的 AI 代理（以 Claude Code 为例）：
```bash
claude mcp add mimir -- python3 $(pwd)/mimir/mcp_server.py
```

## 🔄 记忆生命周期 (The Rite of Memory)

Mimir 会静默守护你的对话。每当对话积累 15 条消息，仪式便会自动开启：
1.  **Snapshot:** 捕捉当前对话快照。
2.  **Normalize:** 剥离干扰杂讯，提纯核心文本。
3.  **Extract:** 自动识别并提取 **Decisions (决策)**, **Milestones (里程碑)**, **Problems (难题)**。
4.  **Generates:** 将这些记忆编织成一段确定的 Python 代码，存入智慧之泉（Skeleton Index）。

## 📜 常用指令

- `mimir status`: 检视当前智慧之泉中积累的记忆总量与分布。
- `mimir search "query"`: 在记忆骨架中精确寻找往昔的残片。
- `mimir wake-up`: 获取最新的上下文简报，快速同步 AI 的认知状态。

---

> **Mimir**: *因为一颗充满智慧的头颅，胜过一具臃肿凡庸的躯壳。*

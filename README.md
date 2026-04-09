# 🧠 Mimir

> *"Mimir's head whispers the secrets of the Nine Realms to the All-Father; even without a body, wisdom remains eternal."*

**Mimir** is a deterministic, pure-Python “skeleton memory” system for AI agents (such as Claude Code and Codex). It provides lightweight, long-term context tracking and relationship memory without vector databases or heavy infrastructure.

[中文文档 (Chinese)](./readme_cn.md)

---

## ⚖️ Core Philosophy: Headless Wisdom

In Norse mythology, Mimir loses his body but keeps his wisdom. This project follows that idea:
- **Headless (No DB stack):** No Qdrant, no Ollama, no SQLite. Memory is code.
- **Deterministic:** Memory is not probabilistic vector retrieval; it is structured Python skeleton modules.
- **Ageless:** Decisions, milestones, and relationships are extracted across sessions into a durable memory network.

## 🛠️ Key Features

- **Pythonic Skeletons:** Conversation transcripts are mined into executable Python modules under `.mimir/skeleton/`, supporting AST-level retrieval.
- **Relationship Layer:** Repeated topics, files, and key decisions are linked across sessions.
- **Zero-Latency Search:** Local rule-based ranking gives fast, predictable retrieval.
- **MCP Native:** Designed for Model Context Protocol tooling, so agents can wake memory via tools like `mimir_status`.

## 🚀 Quick Start

### 1. Install
```bash
pip install -e .
```

### 2. Configure MCP
Example (Claude Code):
```bash
claude mcp add mimir -- python3 $(pwd)/mimir/mcp_server.py
```

Example (Codex):
```bash
codex mcp add --env PYTHONPATH=$(pwd) mimir -- python3 -m mimir.mcp_server
```

## 🔄 Memory Lifecycle

Mimir runs in the background. By default, after every 15 user turns:
1. **Snapshot:** capture the current transcript state.
2. **Normalize:** remove low-value noise.
3. **Extract:** identify **Decisions**, **Milestones**, and **Problems**.
4. **Generate:** emit deterministic Python skeleton modules into the memory index.

## 📜 Common Commands

- `mimir status`: inspect current memory distribution.
- `mimir search "query"`: search memory skeletons.
- `mimir wake-up`: get a compact context briefing.

---

> **Mimir**: a wise head is better than a heavy body. by gpt5.4

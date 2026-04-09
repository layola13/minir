from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import re
from typing import Dict, List, Sequence, Tuple

FILE_PATH_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|js|ts|tsx|jsx|go|rs|rb|java|json|yaml|yml|toml|md|sh|sql|css|html)")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
NOISE_MESSAGE_PREFIXES = (
    "<local-command-caveat>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<system-reminder>",
)

STOPWORDS = {
    "about",
    "after",
    "agent",
    "already",
    "and",
    "assistant",
    "autosave",
    "because",
    "before",
    "between",
    "change",
    "claude",
    "code",
    "could",
    "current",
    "decision",
    "discussed",
    "done",
    "each",
    "file",
    "files",
    "for",
    "from",
    "good",
    "have",
    "into",
    "its",
    "just",
    "keep",
    "keeps",
    "let",
    "like",
    "maybe",
    "memory",
    "messages",
    "need",
    "our",
    "problem",
    "project",
    "references",
    "relationship",
    "repeated",
    "save",
    "saved",
    "session",
    "should",
    "show",
    "sounds",
    "stay",
    "store",
    "summary",
    "system",
    "task",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "through",
    "topic",
    "topics",
    "user",
    "using",
    "visible",
    "want",
    "with",
}


def _is_noise_message(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return stripped.startswith(NOISE_MESSAGE_PREFIXES)


def _extract_files(text: str) -> List[str]:
    return sorted({match.rstrip('.,:;)]}') for match in FILE_PATH_RE.findall(text)})


def _extract_tokens(text: str) -> List[str]:
    tokens = []
    for token in TOKEN_RE.findall(text.lower()):
        if token in STOPWORDS:
            continue
        if token.isdigit() or len(token) < 4:
            continue
        if token in {"jsonl", "yaml", "yml", "toml", "html", "css", "sql"}:
            continue
        tokens.append(token)
    return tokens


def _topic_priority(token: str) -> tuple[int, int, str]:
    preferred = 0
    if "/" in token or "_" in token or "-" in token:
        preferred -= 1
    if token.endswith(("ing", "tion", "ment", "ity", "ship")):
        preferred -= 1
    return (preferred, -len(token), token)


def _memory_topics(memory: Dict[str, object]) -> List[str]:
    content = str(memory.get("content", ""))
    token_counts = Counter(_extract_tokens(content))
    ranked = sorted(token_counts.items(), key=lambda item: (-item[1], _topic_priority(item[0])))
    return [token for token, _ in ranked[:3]]


def _memory_files(memory: Dict[str, object]) -> List[str]:
    return _extract_files(str(memory.get("content", "")))


def _memory_preview(memory: Dict[str, object], limit: int = 120) -> str:
    return str(memory.get("content", "")).replace("\n", " ").strip()[:limit]


def _node_type_indexes(memories: Sequence[Dict[str, object]]) -> Dict[str, List[int]]:
    indexes: Dict[str, List[int]] = defaultdict(list)
    for idx, memory in enumerate(memories):
        indexes[str(memory.get("memory_type", "general"))].append(idx)
    return dict(sorted(indexes.items()))


def _node_file_indexes(memories: Sequence[Dict[str, object]]) -> Dict[str, List[int]]:
    indexes: Dict[str, List[int]] = defaultdict(list)
    for idx, memory in enumerate(memories):
        for path in _memory_files(memory):
            indexes[path].append(idx)
    return dict(sorted(indexes.items()))


def _node_topic_indexes(memories: Sequence[Dict[str, object]]) -> Dict[str, List[int]]:
    indexes: Dict[str, List[int]] = defaultdict(list)
    for idx, memory in enumerate(memories):
        for topic in _memory_topics(memory):
            indexes[topic].append(idx)
    return dict(sorted(indexes.items()))


def _topic_groups(memories: Sequence[Dict[str, object]]) -> List[dict]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, memory in enumerate(memories):
        for topic in _memory_topics(memory):
            groups[topic].append(idx)
    return [
        {"name": topic, "memory_indexes": indexes}
        for topic, indexes in sorted(groups.items())
        if len(indexes) >= 2
    ]


def _file_groups(memories: Sequence[Dict[str, object]]) -> List[dict]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, memory in enumerate(memories):
        for path in _extract_files(str(memory.get("content", ""))):
            groups[path].append(idx)
    return [
        {"path": path, "memory_indexes": indexes}
        for path, indexes in sorted(groups.items())
        if len(indexes) >= 2
    ]


def _pattern_groups(memories: Sequence[Dict[str, object]]) -> List[dict]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, memory in enumerate(memories):
        groups[str(memory.get("memory_type", "general"))].append(idx)
    return [
        {"name": pattern, "memory_indexes": indexes}
        for pattern, indexes in sorted(groups.items())
        if len(indexes) >= 2
    ]


def _co_occurrences(memories: Sequence[Dict[str, object]]) -> List[dict]:
    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for memory in memories:
        topics = sorted(set(_memory_topics(memory)))
        for pair in combinations(topics, 2):
            pair_counts[pair] += 1
    return [
        {"left": pair[0], "right": pair[1], "count": count}
        for pair, count in sorted(pair_counts.items())
        if count >= 2
    ]


def _hard_edges(memories: Sequence[Dict[str, object]]) -> List[dict]:
    edges = []
    for idx in range(len(memories) - 1):
        left = str(memories[idx].get("memory_type", "general"))
        right = str(memories[idx + 1].get("memory_type", "general"))
        if left == right:
            edges.append({"source": idx, "target": idx + 1, "relation": "follows_from", "label": None})
    return edges


def _quoted(value: str) -> str:
    return repr(value)


def _extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return " ".join(part.strip() for part in parts if str(part).strip()).strip()
    if isinstance(content, dict):
        return str(content.get("text", "")).strip()
    return ""


def _extract_session_messages(snapshot_file: str) -> List[dict]:
    messages: List[dict] = []
    snapshot_path = Path(snapshot_file)
    if not snapshot_path.exists():
        return messages
    for line in snapshot_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant", "human"}:
            continue
        text = _extract_message_text(message.get("content", ""))
        if not text:
            continue
        if _is_noise_message(text):
            continue
        normalized_role = "user" if role in {"user", "human"} else "assistant"
        messages.append({"role": normalized_role, "content": text})
    return messages


def _task_description(messages: Sequence[dict]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return str(message.get("content", "")).replace("\n", " ").strip()
    return ""


def _task_topics(messages: Sequence[dict], memories: Sequence[Dict[str, object]]) -> List[str]:
    counts: Counter[str] = Counter()
    for message in messages:
        if message.get("role") != "user":
            continue
        counts.update(_extract_tokens(str(message.get("content", ""))))
    if not counts:
        for memory in memories:
            counts.update(_memory_topics(memory))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], _topic_priority(item[0])))
    return [token for token, _ in ranked[:3]]


def _summary_module_text(snapshot_name: str, task_description: str, task_topics: Sequence[str], stats: dict) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        f"SNAPSHOT_NAME = {_quoted(snapshot_name)}",
        f"TASK_DESCRIPTION = {_quoted(task_description)}",
        f"TASK_TOPICS = {list(task_topics)!r}",
        f"MEMORY_COUNT = {int(stats.get('memory_count', 0))!r}",
        f"TOPIC_CLUSTER_COUNT = {int(stats.get('topic_count', 0))!r}",
        f"FILE_GROUP_COUNT = {int(stats.get('file_group_count', 0))!r}",
        f"PATTERN_COUNT = {int(stats.get('pattern_count', 0))!r}",
        f"CO_OCCURRENCE_COUNT = {int(stats.get('co_occurrence_count', 0))!r}",
        f"EDGE_COUNT = {int(stats.get('edge_count', 0))!r}",
        "",
        "def snapshot_overview() -> dict:",
        "    return {",
        "        'snapshot_name': SNAPSHOT_NAME,",
        "        'task_description': TASK_DESCRIPTION,",
        "        'task_topics': list(TASK_TOPICS),",
        "        'memory_count': MEMORY_COUNT,",
        "        'topic_cluster_count': TOPIC_CLUSTER_COUNT,",
        "        'file_group_count': FILE_GROUP_COUNT,",
        "        'pattern_count': PATTERN_COUNT,",
        "        'co_occurrence_count': CO_OCCURRENCE_COUNT,",
        "        'edge_count': EDGE_COUNT,",
        "    }",
        "",
    ]
    return "\n".join(lines)


def build_relationship_skeleton(memories: Sequence[Dict[str, object]]) -> Tuple[str, dict]:
    topic_groups = _topic_groups(memories)
    file_groups = _file_groups(memories)
    pattern_groups = _pattern_groups(memories)
    co_occurrences = _co_occurrences(memories)
    hard_edges = _hard_edges(memories)
    node_type_indexes = _node_type_indexes(memories)
    node_topic_indexes = _node_topic_indexes(memories)
    node_file_indexes = _node_file_indexes(memories)

    init_lines = [
        "from mimir.summary import SNAPSHOT_NAME, TASK_DESCRIPTION, TASK_TOPICS, snapshot_overview",
        "from mimir.nodes import MemoryNode, NODES, NODE_TYPES, NODE_TOPICS, NODE_FILES",
        "from mimir.topics import TopicCluster",
        "from mimir.files import FileReference",
        "from mimir.patterns import PatternGroup",
        "from mimir.edges import RelationGraph",
        "",
        "graph = RelationGraph()",
        "",
    ]

    nodes_lines = [
        "from __future__ import annotations",
        "",
        "class MemoryNode:",
        "    def __init__(self, index: int, memory_type: str, preview: str, topics: list[str], files: list[str]) -> None:",
        "        self.index = index",
        "        self.memory_type = memory_type",
        "        self.preview = preview",
        "        self.topics = topics",
        "        self.files = files",
        "",
        "    def signature(self) -> tuple[int, str]:",
        "        return (self.index, self.memory_type)",
        "",
        "NODES = [",
    ]
    for idx, memory in enumerate(memories):
        preview = _memory_preview(memory)
        topics = _memory_topics(memory)
        files = _memory_files(memory)
        nodes_lines.append(
            f"    MemoryNode(index={idx}, memory_type={_quoted(str(memory.get('memory_type', 'general')))}, preview={_quoted(preview)}, topics={topics!r}, files={files!r}),"
        )
    nodes_lines.extend(
        [
            "]",
            "",
            f"NODE_TYPES = {node_type_indexes!r}",
            f"NODE_TOPICS = {node_topic_indexes!r}",
            f"NODE_FILES = {node_file_indexes!r}",
            "",
        ]
    )

    topics_lines = [
        "from __future__ import annotations",
        "",
        "class TopicCluster:",
        "    def __init__(self, name: str, members: list[int]) -> None:",
        "        self.name = name",
        "        self.members = members",
        "",
        "    def references(self) -> list[int]:",
        "        return list(self.members)",
        "",
        "TOPIC_CLUSTERS = [",
    ]
    for group in topic_groups:
        topics_lines.append(f"    TopicCluster(name={_quoted(group['name'])}, members={group['memory_indexes']!r}),")
    topics_lines.append("]")
    topics_lines.append("")

    files_lines = [
        "from __future__ import annotations",
        "",
        "class FileReference:",
        "    def __init__(self, path: str, members: list[int]) -> None:",
        "        self.path = path",
        "        self.members = members",
        "",
        "    def touches(self) -> list[int]:",
        "        return list(self.members)",
        "",
        "FILE_REFERENCES = [",
    ]
    for group in file_groups:
        files_lines.append(f"    FileReference(path={_quoted(group['path'])}, members={group['memory_indexes']!r}),")
    files_lines.append("]")
    files_lines.append("")

    patterns_lines = [
        "from __future__ import annotations",
        "",
        "class PatternGroup:",
        "    def __init__(self, name: str, members: list[int]) -> None:",
        "        self.name = name",
        "        self.members = members",
        "",
        "    def repeats(self) -> list[int]:",
        "        return list(self.members)",
        "",
        "REPEATED_PATTERNS = [",
    ]
    for group in pattern_groups:
        patterns_lines.append(f"    PatternGroup(name={_quoted(group['name'])}, members={group['memory_indexes']!r}),")
    patterns_lines.append("]")
    patterns_lines.append("")

    edges_lines = [
        "from __future__ import annotations",
        "",
        "from mimir.nodes import NODES",
        "from mimir.topics import TOPIC_CLUSTERS",
        "from mimir.files import FILE_REFERENCES",
        "from mimir.patterns import REPEATED_PATTERNS",
        "",
        "class RelationGraph:",
        f"    memory_count = {len(memories)}",
        "",
        "    topic_clusters = TOPIC_CLUSTERS",
        "    file_references = FILE_REFERENCES",
        "    repeated_patterns = REPEATED_PATTERNS",
        "",
        f"    co_occurrences = {co_occurrences!r}",
        f"    hard_edges = {hard_edges!r}",
        "",
        "    def same_topic_neighbors(self, node_index: int) -> list[tuple[int, str]]:",
        "        neighbors: list[tuple[int, str]] = []",
        "        seen: set[tuple[int, str]] = set()",
        "        for cluster in self.topic_clusters:",
        "            if node_index not in cluster.members:",
        "                continue",
        "            for member in cluster.members:",
        "                if member == node_index:",
        "                    continue",
        "                item = (member, cluster.name)",
        "                if item in seen:",
        "                    continue",
        "                seen.add(item)",
        "                neighbors.append(item)",
        "        return neighbors",
        "",
        "    def same_file_neighbors(self, node_index: int) -> list[tuple[int, str]]:",
        "        neighbors: list[tuple[int, str]] = []",
        "        seen: set[tuple[int, str]] = set()",
        "        for reference in self.file_references:",
        "            if node_index not in reference.members:",
        "                continue",
        "            for member in reference.members:",
        "                if member == node_index:",
        "                    continue",
        "                item = (member, reference.path)",
        "                if item in seen:",
        "                    continue",
        "                seen.add(item)",
        "                neighbors.append(item)",
        "        return neighbors",
        "",
        "    def same_pattern_neighbors(self, node_index: int) -> list[tuple[int, str]]:",
        "        neighbors: list[tuple[int, str]] = []",
        "        seen: set[tuple[int, str]] = set()",
        "        for pattern in self.repeated_patterns:",
        "            if node_index not in pattern.members:",
        "                continue",
        "            for member in pattern.members:",
        "                if member == node_index:",
        "                    continue",
        "                item = (member, pattern.name)",
        "                if item in seen:",
        "                    continue",
        "                seen.add(item)",
        "                neighbors.append(item)",
        "        return neighbors",
        "",
        "    def neighbors(self, node_index: int) -> list[tuple[int, str, str | None]]:",
        "        merged: list[tuple[int, str, str | None]] = []",
        "        seen: set[tuple[int, str, str | None]] = set()",
        "        for edge in self.hard_edges:",
        "            if edge['source'] == node_index:",
        "                item = (edge['target'], edge['relation'], edge['label'])",
        "                if item not in seen:",
        "                    seen.add(item)",
        "                    merged.append(item)",
        "            elif edge['target'] == node_index:",
        "                item = (edge['source'], edge['relation'], edge['label'])",
        "                if item not in seen:",
        "                    seen.add(item)",
        "                    merged.append(item)",
        "        for neighbor, label in self.same_topic_neighbors(node_index):",
        "            item = (neighbor, 'same_topic_as', label)",
        "            if item not in seen:",
        "                seen.add(item)",
        "                merged.append(item)",
        "        for neighbor, label in self.same_file_neighbors(node_index):",
        "            item = (neighbor, 'mentions_same_file', label)",
        "            if item not in seen:",
        "                seen.add(item)",
        "                merged.append(item)",
        "        for neighbor, label in self.same_pattern_neighbors(node_index):",
        "            item = (neighbor, 'repeats_pattern', label)",
        "            if item not in seen:",
        "                seen.add(item)",
        "                merged.append(item)",
        "        return merged",
        "",
        "    def topics_for(self, node_index: int) -> list[str]:",
        "        return [cluster.name for cluster in self.topic_clusters if node_index in cluster.members]",
        "",
        "    def files_for(self, node_index: int) -> list[str]:",
        "        return [reference.path for reference in self.file_references if node_index in reference.members]",
        "",
        "    def repeated_types(self) -> list[str]:",
        "        return [pattern.name for pattern in self.repeated_patterns]",
        "",
    ]

    package_text = {
        "__init__.py": "\n".join(init_lines),
        "nodes.py": "\n".join(nodes_lines),
        "topics.py": "\n".join(topics_lines),
        "files.py": "\n".join(files_lines),
        "patterns.py": "\n".join(patterns_lines),
        "edges.py": "\n".join(edges_lines),
    }

    preview = "\n\n".join(f"# {name}\n{text}" for name, text in package_text.items())
    stats = {
        "memory_count": len(memories),
        "topic_count": len(topic_groups),
        "file_group_count": len(file_groups),
        "pattern_count": len(pattern_groups),
        "co_occurrence_count": len(co_occurrences),
        "edge_count": len(hard_edges),
    }
    return preview, stats


def skeleton_output_path(workspace_root: str) -> Path:
    return Path(workspace_root) / ".mimir" / "skeleton"


def _snapshot_package_name(snapshot_file: str) -> str:
    return f"snapshot_{Path(snapshot_file).stem}"


def snapshot_skeleton_output_path(workspace_root: str, snapshot_file: str) -> Path:
    snapshot_name = _snapshot_package_name(snapshot_file)
    return skeleton_output_path(workspace_root) / snapshot_name


def index_output_path(workspace_root: str) -> Path:
    return skeleton_output_path(workspace_root) / "__index__.py"


def _build_package(preview: str) -> Dict[str, str]:
    package: Dict[str, str] = {}
    current_name = None
    current_lines: List[str] = []
    for line in preview.splitlines():
        if line.startswith("# ") and line.endswith(".py"):
            if current_name is not None:
                package[current_name] = "\n".join(current_lines).strip() + "\n"
            current_name = line[2:]
            current_lines = []
            continue
        current_lines.append(line)
    if current_name is not None:
        package[current_name] = "\n".join(current_lines).strip() + "\n"
    return package


def _write_package(output_dir: Path, package: Dict[str, str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in package.items():
        (output_dir / name).write_text(content, encoding="utf-8")


def _read_literal_assignment(file_path: Path, name: str, fallback):
    if not file_path.exists():
        return fallback
    prefix = f"{name} = "
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return ast.literal_eval(line[len(prefix):])
    return fallback


def _snapshot_summary(snapshot_dir: Path) -> dict:
    summary_path = snapshot_dir / "summary.py"
    nodes_path = snapshot_dir / "nodes.py"
    edges_path = snapshot_dir / "edges.py"
    node_types = _read_literal_assignment(nodes_path, "NODE_TYPES", {})
    node_topics = _read_literal_assignment(nodes_path, "NODE_TOPICS", {})
    node_files = _read_literal_assignment(nodes_path, "NODE_FILES", {})
    memory_count = _read_literal_assignment(edges_path, "    memory_count", 0)
    task_description = _read_literal_assignment(summary_path, "TASK_DESCRIPTION", "")
    task_topics = _read_literal_assignment(summary_path, "TASK_TOPICS", [])
    top_topics = sorted(node_topics, key=lambda item: (-len(node_topics[item]), item))[:3]
    top_files = sorted(node_files, key=lambda item: (-len(node_files[item]), item))[:3]
    return {
        "name": snapshot_dir.name,
        "summary_module": f"{snapshot_dir.name}.summary",
        "nodes_module": f"{snapshot_dir.name}.nodes",
        "edges_module": f"{snapshot_dir.name}.edges",
        "memory_count": memory_count,
        "memory_types": sorted(node_types),
        "task_description": task_description,
        "task_topics": list(task_topics),
        "top_topics": top_topics,
        "top_files": top_files,
    }


def _global_summary(snapshots: Sequence[dict]) -> dict:
    topic_counts: Counter[str] = Counter()
    file_counts: Counter[str] = Counter()
    task_topic_counts: Counter[str] = Counter()
    total_memory_count = 0
    for snapshot in snapshots:
        total_memory_count += int(snapshot.get("memory_count", 0))
        for topic in snapshot.get("top_topics", []):
            topic_counts[str(topic)] += 1
        for path in snapshot.get("top_files", []):
            file_counts[str(path)] += 1
        for topic in snapshot.get("task_topics", []):
            task_topic_counts[str(topic)] += 1
    return {
        "snapshot_count": len(snapshots),
        "total_memory_count": total_memory_count,
        "global_top_topics": [topic for topic, _ in topic_counts.most_common(5)],
        "global_top_files": [path for path, _ in file_counts.most_common(5)],
        "global_task_topics": [topic for topic, _ in task_topic_counts.most_common(5)],
    }


def _write_index(root_dir: Path) -> None:
    snapshot_dirs = sorted(path for path in root_dir.iterdir() if path.is_dir()) if root_dir.exists() else []
    snapshots = [_snapshot_summary(path) for path in snapshot_dirs]
    latest_snapshot = snapshots[-1]["name"] if snapshots else None
    global_summary = _global_summary(snapshots)
    lines = [
        "# __index__.py  (auto-generated navigation bus)",
        "# ════════════════════════════════════════════════════════════════",
        "# CONVERSATION SKELETON INDEX — compact navigation layer",
        "# Read this file first, then open a specific snapshot package only if needed.",
        "# ════════════════════════════════════════════════════════════════",
        "from __future__ import annotations",
        "",
        "# ── 1. Global Overview ─────────────────────────────────────────",
        f"SNAPSHOT_COUNT = {global_summary['snapshot_count']!r}",
        f"TOTAL_MEMORY_COUNT = {global_summary['total_memory_count']!r}",
        f"GLOBAL_TOP_TOPICS = {global_summary['global_top_topics']!r}",
        f"GLOBAL_TOP_FILES = {global_summary['global_top_files']!r}",
        f"GLOBAL_TASK_TOPICS = {global_summary['global_task_topics']!r}",
        "",
        "# ── 2. Snapshot Routing ────────────────────────────────────────",
        f"SNAPSHOTS = {[item['name'] for item in snapshots]!r}",
        f"LATEST_SNAPSHOT = {latest_snapshot!r}",
        f"SNAPSHOT_SUMMARIES = {snapshots!r}",
        "",
        "def available_snapshots() -> list[str]:",
        "    return list(SNAPSHOTS)",
        "",
        "def latest_snapshot() -> str | None:",
        "    return LATEST_SNAPSHOT",
        "",
        "def summary_for(snapshot_name: str) -> dict | None:",
        "    for item in SNAPSHOT_SUMMARIES:",
        "        if item['name'] == snapshot_name:",
        "            return dict(item)",
        "    return None",
        "",
        "def summary_module_for(snapshot_name: str) -> str | None:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return None",
        "    return summary['summary_module']",
        "",
        "def nodes_module_for(snapshot_name: str) -> str | None:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return None",
        "    return summary['nodes_module']",
        "",
        "def edges_module_for(snapshot_name: str) -> str | None:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return None",
        "    return summary['edges_module']",
        "",
        "def task_topics(snapshot_name: str) -> list[str]:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return []",
        "    return list(summary['task_topics'])",
        "",
        "def task_description(snapshot_name: str) -> str | None:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return None",
        "    return summary['task_description']",
        "",
        "def top_topics(snapshot_name: str) -> list[str]:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return []",
        "    return list(summary['top_topics'])",
        "",
        "def top_files(snapshot_name: str) -> list[str]:",
        "    summary = summary_for(snapshot_name)",
        "    if summary is None:",
        "        return []",
        "    return list(summary['top_files'])",
        "",
        "def global_overview() -> dict:",
        "    return {",
        "        'snapshot_count': SNAPSHOT_COUNT,",
        "        'total_memory_count': TOTAL_MEMORY_COUNT,",
        "        'global_top_topics': list(GLOBAL_TOP_TOPICS),",
        "        'global_top_files': list(GLOBAL_TOP_FILES),",
        "        'global_task_topics': list(GLOBAL_TASK_TOPICS),",
        "        'latest_snapshot': LATEST_SNAPSHOT,",
        "    }",
        "",
    ]
    root_dir.mkdir(parents=True, exist_ok=True)
    (root_dir / "__index__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_relationship_skeleton(
    workspace_root: str,
    snapshot_file: str,
    session_id: str,
    memories: Sequence[Dict[str, object]],
) -> Tuple[Path, dict]:
    del session_id
    root_dir = skeleton_output_path(workspace_root)
    output_dir = snapshot_skeleton_output_path(workspace_root, snapshot_file)
    preview, stats = build_relationship_skeleton(memories)
    package = _build_package(preview)
    messages = _extract_session_messages(snapshot_file)
    snapshot_name = _snapshot_package_name(snapshot_file)
    package["summary.py"] = _summary_module_text(
        snapshot_name=snapshot_name,
        task_description=_task_description(messages),
        task_topics=_task_topics(messages, memories),
        stats=stats,
    )
    _write_package(output_dir, package)
    _write_index(root_dir)
    return output_dir, stats

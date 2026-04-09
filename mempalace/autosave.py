from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .conversation_skeleton import write_relationship_skeleton
from .general_extractor import extract_memories
from .normalize import normalize
from .qdrant_store import get_store

FILE_ACTION_PATTERNS = {
    "created": re.compile(r"\b(create|created|add|added|new file)\b", re.I),
    "edited": re.compile(r"\b(edit|edited|modify|modified|update|updated|change|changed|patch)\b", re.I),
    "deleted": re.compile(r"\b(delete|deleted|remove|removed)\b", re.I),
}
FILE_PATH_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|js|ts|tsx|jsx|go|rs|rb|java|json|yaml|yml|toml|md|sh|sql|css|html)")


def _drawer_id(source_file: str, room: str, chunk_index: int) -> str:
    digest = hashlib.md5(f"{source_file}:{room}:{chunk_index}".encode()).hexdigest()[:16]
    return f"drawer_autosave_{room}_{digest}"


def _upsert_text(store, text: str, wing: str, room: str, source_file: str, added_by: str, chunk_index: int = 0, extra: Optional[dict] = None) -> None:
    metadata = {
        "wing": wing,
        "room": room,
        "source_file": source_file,
        "chunk_index": chunk_index,
        "added_by": added_by,
        "filed_at": datetime.now().isoformat(),
        "autosave": True,
    }
    if extra:
        metadata.update(extra)
    store.upsert_drawer(_drawer_id(source_file, room, chunk_index), text, metadata)


def _git_repo_root(workspace_root: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", workspace_root, "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def _git_diff(repo_root: str) -> str:
    commands = [
        ["git", "-C", repo_root, "diff", "--no-ext-diff", "--binary", "--", "."],
        ["git", "-C", repo_root, "diff", "--no-ext-diff", "--binary", "--cached", "--", "."],
    ]
    parts: List[str] = []
    for cmd in commands:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.stdout.strip():
            parts.append(result.stdout.strip())
    return "\n\n".join(parts).strip()


def _summarize_file_changes(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    changes: Dict[str, set] = {"created": set(), "edited": set(), "deleted": set()}
    for line in lines:
        action = None
        for name, pattern in FILE_ACTION_PATTERNS.items():
            if pattern.search(line):
                action = name
                break
        if not action:
            continue
        for match in FILE_PATH_RE.findall(line):
            changes[action].add(match)
    sections = []
    for action in ("created", "edited", "deleted"):
        paths = sorted(changes[action])
        if paths:
            sections.append(f"{action}:\n" + "\n".join(f"- {path}" for path in paths))
    return "\n\n".join(sections)


def persist_autosave(
    snapshot_file: str,
    wing: str,
    agent: str,
    workspace_root: str,
    trigger: str,
    session_id: str = "unknown",
) -> Tuple[int, bool]:
    snapshot_path = Path(snapshot_file)
    source_file = str(snapshot_path)
    normalized = normalize(source_file)
    store = get_store()

    memories = extract_memories(normalized)
    memory_count = 0
    for idx, memory in enumerate(memories):
        room = f"autosave-{memory['memory_type']}"
        _upsert_text(
            store,
            memory["content"],
            wing,
            room,
            source_file,
            agent,
            idx,
            {"trigger": trigger, "memory_type": memory["memory_type"]},
        )
        memory_count += 1

    skeleton_dir, _ = write_relationship_skeleton(workspace_root, source_file, session_id, memories)
    wrote_skeleton = skeleton_dir.exists()

    repo_root = _git_repo_root(workspace_root)
    if repo_root:
        diff = _git_diff(repo_root)
        if diff:
            _upsert_text(
                store,
                diff,
                wing,
                "code-diff",
                source_file,
                agent,
                0,
                {"trigger": trigger, "workspace_root": workspace_root, "repo_root": repo_root},
            )
            return memory_count, True
        return memory_count, wrote_skeleton

    summary = _summarize_file_changes(normalized)
    if summary:
        _upsert_text(
            store,
            summary,
            wing,
            "code-summary",
            source_file,
            agent,
            0,
            {"trigger": trigger, "workspace_root": workspace_root},
        )
        return memory_count, True
    return memory_count, wrote_skeleton


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Persist selective autosave memories")
    parser.add_argument("snapshot_file")
    parser.add_argument("--wing", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--session-id", default="unknown")
    args = parser.parse_args()

    memory_count, code_saved = persist_autosave(
        snapshot_file=args.snapshot_file,
        wing=args.wing,
        agent=args.agent,
        workspace_root=args.workspace_root,
        trigger=args.trigger,
        session_id=args.session_id,
    )
    return 0 if (memory_count > 0 or code_saved) else 1


if __name__ == "__main__":
    raise SystemExit(main())

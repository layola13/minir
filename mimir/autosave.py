from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mimir.conversation_skeleton import write_relationship_skeleton
from mimir.general_extractor import extract_memories
from mimir.normalize import normalize

FILE_ACTION_PATTERNS = {
    "created": re.compile(r"\b(create|created|add|added|new file)\b", re.I),
    "edited": re.compile(r"\b(edit|edited|modify|modified|update|updated|change|changed|patch)\b", re.I),
    "deleted": re.compile(r"\b(delete|deleted|remove|removed)\b", re.I),
}
FILE_PATH_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|js|ts|tsx|jsx|go|rs|rb|java|json|yaml|yml|toml|md|sh|sql|css|html)")


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
    """
    Persist conversation memories exclusively as a relationship skeleton.
    Returns (memory_count, wrote_skeleton).
    """
    snapshot_path = Path(snapshot_file)
    source_file = str(snapshot_path)
    
    # 1. Normalize and extract memories
    normalized = normalize(source_file)
    memories = extract_memories(normalized)
    
    # 2. Write the Python-like relationship skeleton (The core memory)
    skeleton_dir, _ = write_relationship_skeleton(workspace_root, source_file, session_id, memories)
    wrote_skeleton = skeleton_dir.exists()

    # 3. Handle code context (still stored as files or via skeleton later)
    # For now, we keep the return indicating if we handled the session.
    memory_count = len(memories)
    
    return memory_count, wrote_skeleton


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Persist selective autosave memories (Skeleton-only)")
    parser.add_argument("snapshot_file")
    parser.add_argument("--wing", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--session-id", default="unknown")
    args = parser.parse_args()

    memory_count, wrote_skeleton = persist_autosave(
        snapshot_file=args.snapshot_file,
        wing=args.wing,
        agent=args.agent,
        workspace_root=args.workspace_root,
        trigger=args.trigger,
        session_id=args.session_id,
    )
    
    # Always succeed if we wrote the skeleton, even if 0 memories were extracted (deterministic heart)
    return 0 if wrote_skeleton else 1


if __name__ == "__main__":
    raise SystemExit(main())



if __name__ == "__main__":
    raise SystemExit(main())

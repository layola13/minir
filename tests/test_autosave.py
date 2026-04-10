from mimir.autosave import persist_autosave, _summarize_file_changes
from mimir.conversation_skeleton import index_output_path, snapshot_skeleton_output_path
import json
import os
from pathlib import Path
import subprocess

def _patch_memories(monkeypatch, memories):
    monkeypatch.setattr("mimir.autosave.extract_memories", lambda normalized: memories)

def _sample_memories():
    return [
        {
            "content": "We should keep a relationship skeleton for mimir/autosave.py.",
            "memory_type": "decision",
            "chunk_index": 0,
        },
        {
            "content": "The relationship skeleton should link repeated mentions of mimir/autosave.py.",
            "memory_type": "decision",
            "chunk_index": 1,
        },
    ]

def test_non_git_file_summary_extraction():
    text = "Created src/new_feature.py\nEdited mimir/normalize.py\nDeleted old_notes.md\n"
    summary = _summarize_file_changes(text)
    assert "created:" in summary
    assert "- src/new_feature.py" in summary
    assert "edited:" in summary
    assert "- mimir/normalize.py" in summary
    assert "deleted:" in summary
    assert "- old_notes.md" in summary

def test_persist_autosave_writes_skeleton_package(tmp_path, monkeypatch):
    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Created src/new_feature.py"}}\n'
        '{"message": {"role": "assistant", "content": "Okay"}}\n',
        encoding="utf-8",
    )

    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mimir.autosave._git_repo_root", lambda workspace_root: None)

    memory_count, wrote_skeleton = persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-123",
    )

    skeleton_dir = snapshot_skeleton_output_path(str(tmp_path), str(snapshot))
    index_file = index_output_path(str(tmp_path))
    session_file = Path(tmp_path) / ".mimir" / "skeleton" / "sessions" / "session-123.py"

    assert memory_count == 2
    assert wrote_skeleton is True
    assert skeleton_dir.exists()
    assert index_file.exists()
    assert (skeleton_dir / "nodes.py").exists()
    assert session_file.exists()
    assert "SNAPSHOTS" in session_file.read_text(encoding="utf-8")

    index_text = index_file.read_text(encoding="utf-8")
    assert f"snapshot_{snapshot.stem}" in index_text
    assert "LATEST_SNAPSHOT" in index_text
    assert "SESSION_SUMMARIES" in index_text
    assert "session-123" in index_text

def test_save_hook_skeleton_flow(tmp_path):
    repo_root = Path(os.getcwd())
    home = tmp_path / "home"
    hook_state = home / ".mimir" / "hook_state"
    session_id = "hook-test-session"
    transcript = tmp_path / "session.jsonl"

    # 15 user turns
    content = ""
    for i in range(15):
        content += json.dumps({"message": {"role": "user", "content": f"msg {i}"}}) + "\n"
        content += json.dumps({"message": {"role": "assistant", "content": "ok"}}) + "\n"
    transcript.write_text(content, encoding="utf-8")

    payload = json.dumps({
        "session_id": session_id,
        "stop_hook_active": False,
        "transcript_path": str(transcript),
    })

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "PYTHONPATH": str(repo_root),
    }

    result = subprocess.run(
        ["/bin/bash", str(repo_root / "hooks" / "mimir_save_hook.sh")],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 0
    hook_log = (hook_state / "hook.log").read_text(encoding="utf-8")
    assert "TRIGGERING SKELETON SAVE" in hook_log
    assert "SKELETON SAVE persisted successfully" in hook_log

    last_save_file = hook_state / f"{session_id}_last_save"
    assert last_save_file.exists()
    assert last_save_file.read_text().strip() == "15"

def test_persist_autosave_zero_memories_still_succeeds(tmp_path, monkeypatch):
    snapshot = tmp_path / "empty.jsonl"
    snapshot.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")

    _patch_memories(monkeypatch, []) # Zero memories
    monkeypatch.setattr("mimir.autosave._git_repo_root", lambda workspace_root: None)

    memory_count, wrote_skeleton = persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-empty",
    )

    assert memory_count == 0
    assert wrote_skeleton is True
    assert snapshot_skeleton_output_path(str(tmp_path), str(snapshot)).exists()

def test_mcp_server_skeleton_routing(tmp_path, monkeypatch):
    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text('{"message": {"role": "user", "content": "test mcp"}}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    persist_autosave(str(snapshot), "w", "a", str(tmp_path), "stop", "s1")

    from mimir import mcp_server
    res = mcp_server.tool_status()
    assert res["total_drawers"] >= 0
    assert "protocol" in res

    idx = mcp_server.tool_fast_skeleton_index()
    assert idx["exists"] is True

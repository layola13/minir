from mempalace.autosave import persist_autosave, _summarize_file_changes
from mempalace.conversation_skeleton import index_output_path, snapshot_skeleton_output_path
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


class DummyStore:
    def __init__(self, captured):
        self.captured = captured

    def upsert_drawer(self, drawer_id, text, metadata, collection_name=None):
        self.captured.append((drawer_id, text, metadata))




class DummyCollection:
    def __init__(self):
        self.records = []

    def add(self, ids, documents, metadatas):
        for drawer_id, text, metadata in zip(ids, documents, metadatas):
            self.records.append({"id": drawer_id, "document": text, "metadata": metadata})

    def get(self, where=None, include=None):
        matched = []
        for record in self.records:
            meta = record["metadata"]
            if _matches_where(meta, where):
                matched.append(record)
        return {
            "ids": [record["id"] for record in matched],
            "documents": [record["document"] for record in matched],
            "metadatas": [record["metadata"] for record in matched],
        }


class DummyKG:
    def __init__(self):
        self.facts = []

    def add_triple(self, subject, predicate, obj, valid_from=None, source_closet=None, source_file=None):
        record = {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "valid_from": valid_from,
            "source_closet": source_closet,
            "source_file": source_file,
            "current": True,
        }
        self.facts.append(record)
        return f"triple-{len(self.facts)}"

    def invalidate(self, subject, predicate, obj, ended=None):
        for fact in self.facts:
            if fact["subject"] == subject and fact["predicate"] == predicate and fact["object"] == obj and fact.get("current", True):
                fact["current"] = False
                fact["valid_to"] = ended or "today"

    def query_entity(self, name, as_of=None, direction="both"):
        results = []
        for fact in self.facts:
            if direction in ("outgoing", "both") and fact["subject"] == name:
                results.append(
                    {
                        "direction": "outgoing",
                        "subject": fact["subject"],
                        "predicate": fact["predicate"],
                        "object": fact["object"],
                        "valid_from": fact.get("valid_from"),
                        "valid_to": fact.get("valid_to"),
                        "confidence": 1.0,
                        "source_closet": fact.get("source_closet"),
                        "current": fact.get("current", True),
                    }
                )
            if direction in ("incoming", "both") and fact["object"] == name:
                results.append(
                    {
                        "direction": "incoming",
                        "subject": fact["subject"],
                        "predicate": fact["predicate"],
                        "object": fact["object"],
                        "valid_from": fact.get("valid_from"),
                        "valid_to": fact.get("valid_to"),
                        "confidence": 1.0,
                        "source_closet": fact.get("source_closet"),
                        "current": fact.get("current", True),
                    }
                )
        return results

    def timeline(self, entity=None):
        timeline = []
        for fact in self.facts:
            if entity and entity not in {fact["subject"], fact["object"]}:
                continue
            timeline.append(
                {
                    "subject": fact["subject"],
                    "predicate": fact["predicate"],
                    "object": fact["object"],
                    "valid_from": fact.get("valid_from"),
                    "valid_to": fact.get("valid_to"),
                    "current": fact.get("current", True),
                }
            )
        return timeline

    def stats(self):
        current = sum(1 for fact in self.facts if fact.get("current", True))
        expired = len(self.facts) - current
        return {
            "entities": len({fact["subject"] for fact in self.facts} | {fact["object"] for fact in self.facts}),
            "triples": len(self.facts),
            "current_facts": current,
            "expired_facts": expired,
            "relationship_types": sorted({fact["predicate"] for fact in self.facts}),
        }


def _matches_where(metadata, where):
    if not where:
        return True
    if "$and" in where:
        return all(_matches_where(metadata, condition) for condition in where["$and"])
    return all(metadata.get(key) == value for key, value in where.items())


def _patch_store(monkeypatch, captured):
    monkeypatch.setattr("mempalace.autosave.get_store", lambda: DummyStore(captured))


def _patch_memories(monkeypatch, memories):
    monkeypatch.setattr("mempalace.autosave.extract_memories", lambda normalized: memories)


def _sample_memories():
    return [
        {
            "content": "We should keep a relationship skeleton for mempalace/autosave.py.",
            "memory_type": "decision",
            "chunk_index": 0,
        },
        {
            "content": "The relationship skeleton should link repeated mentions of mempalace/autosave.py.",
            "memory_type": "decision",
            "chunk_index": 1,
        },
    ]


def _rooms(captured):
    return [item[2]["room"] for item in captured]


def test_non_git_file_summary_extraction():
    text = "Created src/new_feature.py\nEdited mempalace/normalize.py\nDeleted old_notes.md\n"
    summary = _summarize_file_changes(text)
    assert "created:" in summary
    assert "- src/new_feature.py" in summary
    assert "edited:" in summary
    assert "- mempalace/normalize.py" in summary
    assert "deleted:" in summary
    assert "- old_notes.md" in summary


def test_persist_autosave_non_git_returns_code_summary_and_writes_single_skeleton_package(tmp_path, monkeypatch):
    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Created src/new_feature.py because we need autosave relationship tracking"}}\n'
        '{"message": {"role": "assistant", "content": "Sounds good, let us keep a skeleton"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    memory_count, code_saved = persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-123",
    )

    skeleton_dir = snapshot_skeleton_output_path(str(tmp_path), str(snapshot))
    index_file = index_output_path(str(tmp_path))
    assert memory_count == 2
    assert code_saved is True
    assert "code-summary" in _rooms(captured)
    assert skeleton_dir.exists()
    assert index_file.exists()
    assert not (skeleton_dir.parent / "latest").exists()
    assert (skeleton_dir / "__init__.py").exists()
    assert (skeleton_dir / "summary.py").exists()
    assert (skeleton_dir / "nodes.py").exists()
    assert (skeleton_dir / "topics.py").exists()
    assert (skeleton_dir / "files.py").exists()
    assert (skeleton_dir / "patterns.py").exists()
    assert (skeleton_dir / "edges.py").exists()
    summary_text = (skeleton_dir / "summary.py").read_text(encoding="utf-8")
    assert "TASK_DESCRIPTION = 'Created src/new_feature.py because we need autosave relationship tracking'" in summary_text
    assert "TASK_TOPICS = ['tracking', 'created', 'new_feature']" not in summary_text
    assert "TASK_TOPICS = " in summary_text
    assert "tracking" in summary_text
    assert "created" in summary_text
    assert "new_feature" in summary_text
    assert "snapshot_overview" in summary_text
    edges_text = (skeleton_dir / "edges.py").read_text(encoding="utf-8")
    assert "RelationGraph" in edges_text
    assert "hard_edges" in edges_text
    assert "same_topic_neighbors" in edges_text
    assert "same_file_neighbors" in edges_text
    assert "same_pattern_neighbors" in edges_text
    assert "mempalace/autosave.py" in (skeleton_dir / "nodes.py").read_text(encoding="utf-8")
    index_text = index_file.read_text(encoding="utf-8")
    assert f"snapshot_{snapshot.stem}" in index_text
    assert "SNAPSHOT_SUMMARIES" in index_text
    assert "LATEST_SNAPSHOT" in index_text
    assert "SNAPSHOT_COUNT" in index_text
    assert "TOTAL_MEMORY_COUNT" in index_text
    assert "GLOBAL_TOP_TOPICS" in index_text
    assert "GLOBAL_TOP_FILES" in index_text
    assert "GLOBAL_TASK_TOPICS" in index_text
    assert "summary_module_for" in index_text
    assert "nodes_module_for" in index_text
    assert "edges_module_for" in index_text
    assert "task_topics" in index_text
    assert "task_description" in index_text
    assert "global_overview" in index_text
    assert "top_topics" in index_text
    assert "top_files" in index_text


def test_persist_autosave_git_uses_diff_and_writes_single_skeleton_package(tmp_path, monkeypatch):
    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "We updated normalize.py to fix autosave and keep the relationship skeleton"}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: str(tmp_path))
    monkeypatch.setattr("mempalace.autosave._git_diff", lambda repo_root: "diff --git a/a.py b/a.py\n+print('hi')")

    memory_count, code_saved = persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-456",
    )

    skeleton_dir = snapshot_skeleton_output_path(str(tmp_path), str(snapshot))
    index_file = index_output_path(str(tmp_path))
    assert memory_count == 2
    assert code_saved is True
    assert "code-diff" in _rooms(captured)
    assert any("diff --git" in item[1] for item in captured)
    assert skeleton_dir.exists()
    assert not (skeleton_dir.parent / "latest").exists()
    assert index_file.exists()
    assert (skeleton_dir / "summary.py").exists()
    assert "hard_edges" in (skeleton_dir / "edges.py").read_text(encoding="utf-8")
    assert f"snapshot_{snapshot.stem}" in index_file.read_text(encoding="utf-8")


def test_generated_skeleton_package_methods_are_callable(tmp_path, monkeypatch):
    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Created src/new_feature.py because we need autosave relationship tracking"}}\n'
        '{"message": {"role": "assistant", "content": "Sounds good, let us keep a skeleton"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-789",
    )

    skeleton_dir = snapshot_skeleton_output_path(str(tmp_path), str(snapshot))
    package_name = "generated_skeleton_test"
    spec = importlib.util.spec_from_file_location(package_name, skeleton_dir / "__init__.py", submodule_search_locations=[str(skeleton_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

    graph = module.graph
    assert module.SNAPSHOT_NAME == f"snapshot_{snapshot.stem}"
    assert module.TASK_DESCRIPTION == "Created src/new_feature.py because we need autosave relationship tracking"
    assert set(module.TASK_TOPICS) == {"tracking", "created", "new_feature"}
    assert module.snapshot_overview()["task_description"] == module.TASK_DESCRIPTION
    assert set(module.snapshot_overview()["task_topics"]) == {"tracking", "created", "new_feature"}
    assert graph.topics_for(0)
    assert graph.files_for(0) == ["mempalace/autosave.py"]
    assert graph.repeated_types() == ["decision"]
    neighbors = graph.neighbors(0)
    assert any(item[1] == "same_topic_as" for item in neighbors)
    assert any(item[1] == "mentions_same_file" for item in neighbors)
    assert any(item[1] == "repeats_pattern" for item in neighbors)


def test_save_hook_keeps_successful_autosave_successful(tmp_path):
    repo_root = Path("/home/vscode/projects/mempalace")
    home = tmp_path / "home"
    hook_state = home / ".mempalace" / "hook_state"
    snapshots_root = hook_state / "transcript_snapshots"
    session_id = "hook-regression-session"
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "".join(
            json.dumps({"message": {"role": "user", "content": f"Created src/new_feature_{idx}.py because we need autosave relationship tracking"}}) + "\n"
            for idx in range(15)
        ) + json.dumps({"message": {"role": "assistant", "content": "Sounds good, let us keep a skeleton"}}) + "\n",
        encoding="utf-8",
    )

    payload = json.dumps(
        {
            "session_id": session_id,
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        }
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "PYTHONPATH": str(repo_root),
    }

    result = subprocess.run(
        ["/bin/bash", str(repo_root / "hooks" / "mempal_save_hook.sh")],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "{}"

    last_save_file = hook_state / f"{session_id}_last_save"
    assert last_save_file.exists()
    assert last_save_file.read_text(encoding="utf-8").strip() == "15"

    session_snapshot_dir = snapshots_root / session_id
    assert session_snapshot_dir.exists()
    assert any(path.name.endswith("_stop.jsonl") for path in session_snapshot_dir.iterdir())

    hook_log = (hook_state / "hook.log").read_text(encoding="utf-8")
    assert "TRIGGERING SAVE" in hook_log
    assert "AUTO-SAVE persisted successfully (exit=0)" in hook_log



def test_index_points_to_most_recent_snapshot_without_duplicate_directory(tmp_path, monkeypatch):
    first_snapshot = tmp_path / "20260101_000000_stop.jsonl"
    second_snapshot = tmp_path / "20260101_000100_stop.jsonl"
    for snapshot in (first_snapshot, second_snapshot):
        snapshot.write_text(
            '{"message": {"role": "user", "content": "Created src/new_feature.py because we need autosave relationship tracking"}}\n'
            '{"message": {"role": "assistant", "content": "Sounds good, let us keep a skeleton"}}\n',
            encoding="utf-8",
        )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(first_snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-latest",
    )
    persist_autosave(
        snapshot_file=str(second_snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-latest",
    )

    first_dir = snapshot_skeleton_output_path(str(tmp_path), str(first_snapshot))
    second_dir = snapshot_skeleton_output_path(str(tmp_path), str(second_snapshot))
    index_file = index_output_path(str(tmp_path))
    index_text = index_file.read_text(encoding="utf-8")
    assert first_dir.exists()
    assert second_dir.exists()
    assert not (second_dir.parent / "latest").exists()
    assert "LATEST_SNAPSHOT = 'snapshot_20260101_000100_stop'" in index_text
    assert f"snapshot_{first_snapshot.stem}" in index_text
    assert f"snapshot_{second_snapshot.stem}" in index_text
    assert "summary_module" in index_text
    assert "task_description" in index_text
    assert "Created src/new_feature.py because we need autosave relationship tracking" in index_text




def test_persist_autosave_filters_local_command_caveat_from_task_description(tmp_path, monkeypatch):
    snapshot = tmp_path / "session_noise.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "<local-command-caveat>Caveat: ignore this.</local-command-caveat>"}}\n'
        '{"message": {"role": "user", "content": "Use the new py skeleton to replace the old palace interface."}}\n'
        '{"message": {"role": "assistant", "content": "Okay"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-noise",
    )

    skeleton_dir = snapshot_skeleton_output_path(str(tmp_path), str(snapshot))
    summary_text = (skeleton_dir / "summary.py").read_text(encoding="utf-8")
    assert "local-command-caveat" not in summary_text
    assert "TASK_DESCRIPTION = 'Use the new py skeleton to replace the old palace interface.'" in summary_text



    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Created src/new_feature.py because we need autosave relationship tracking"}}\n'
        '{"message": {"role": "assistant", "content": "Sounds good, let us keep a skeleton"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-mcp",
    )

    monkeypatch.chdir(tmp_path)
    from mempalace import mcp_server

    index_result = mcp_server.tool_skeleton_index()
    assert index_result["exists"] is True
    assert "SNAPSHOT_SUMMARIES" in index_result["index_text"]

    summary_result = mcp_server.tool_skeleton_read(f"snapshot_{snapshot.stem}", "summary")
    assert summary_result["success"] is True
    assert "TASK_DESCRIPTION" in summary_result["content"]
    assert "TASK_TOPICS" in summary_result["content"]



def test_mcp_fast_tools_return_skeleton_results_with_timing(tmp_path, monkeypatch):
    snapshot = tmp_path / "session_fast.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Use the new py skeleton to replace the old palace interface and benchmark search speed."}}\n'
        '{"message": {"role": "assistant", "content": "Okay"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-fast",
    )

    monkeypatch.chdir(tmp_path)
    from mempalace import mcp_server

    status_result = mcp_server.tool_fast_status()
    assert status_result["backend"] == "skeleton"
    assert status_result["protocol"] == mcp_server.PALACE_PROTOCOL
    assert status_result["aaak_dialect"] == mcp_server.AAAK_SPEC
    assert "elapsed_ms" in status_result

    snapshots_result = mcp_server.tool_fast_list_snapshots()
    assert f"snapshot_{snapshot.stem}" in snapshots_result["snapshots"]
    assert "elapsed_ms" in snapshots_result

    summary_result = mcp_server.tool_fast_summary_for(f"snapshot_{snapshot.stem}")
    assert summary_result["summary"]["name"] == f"snapshot_{snapshot.stem}"
    assert "task_description" in summary_result["summary"]
    assert "elapsed_ms" in summary_result

    search_result = mcp_server.tool_fast_search("autosave", limit=5)
    assert search_result["backend"] == "skeleton"
    assert search_result["results"]
    assert "palace_path" in search_result["filters"]
    assert all("text" in result for result in search_result["results"])
    assert all("source_file" in result for result in search_result["results"])
    assert "elapsed_ms" in search_result

    task_search_result = mcp_server.tool_fast_search("benchmark", limit=5)
    assert task_search_result["results"]
    assert any(result.get("task_description") for result in task_search_result["results"])
    assert any(result["score_breakdown"]["task_description_hit"] or result["score_breakdown"]["task_topic_hits"] for result in task_search_result["results"])

    neighbors_result = mcp_server.tool_fast_neighbors(f"snapshot_{snapshot.stem}", 0)
    assert neighbors_result["backend"] == "skeleton"
    assert "neighbors" in neighbors_result
    assert "elapsed_ms" in neighbors_result

    graph_result = mcp_server.tool_fast_graph_stats()
    assert graph_result["backend"] == "skeleton"
    assert graph_result["memory_count"] >= 2
    assert "elapsed_ms" in graph_result


    aaak_result = mcp_server.tool_fast_get_aaak_spec()
    assert aaak_result["backend"] == "skeleton"
    assert "aaak_spec" in aaak_result
    assert "elapsed_ms" in aaak_result

    kg_add_result = mcp_server.tool_fast_kg_add("Alice", "works_on", "MemPalace", valid_from="2026-04-08")
    assert kg_add_result["backend"] == "skeleton"
    assert kg_add_result["success"] is True
    assert "triple_id" in kg_add_result
    assert kg_add_result["fact"] == "Alice → works_on → MemPalace"
    assert "elapsed_ms" in kg_add_result

    kg_query_result = mcp_server.tool_fast_kg_query("Alice")
    assert kg_query_result["backend"] == "skeleton"
    assert kg_query_result["count"] >= 1
    assert any(fact["predicate"] == "works_on" for fact in kg_query_result["facts"])
    assert "elapsed_ms" in kg_query_result

    kg_stats_result = mcp_server.tool_fast_kg_stats()
    assert kg_stats_result["backend"] == "skeleton"
    assert kg_stats_result["triples"] >= 1
    assert "works_on" in kg_stats_result["relationship_types"]
    assert "elapsed_ms" in kg_stats_result

    diary_write_result = mcp_server.tool_fast_diary_write("tester", "remember this", topic="general")
    assert diary_write_result["backend"] == "skeleton"
    assert diary_write_result["success"] is True
    assert "entry_id" in diary_write_result
    assert "elapsed_ms" in diary_write_result

    diary_read_result = mcp_server.tool_fast_diary_read("tester")
    assert diary_read_result["backend"] == "skeleton"
    assert diary_read_result["total"] >= 1
    assert any(entry["content"] == "remember this" for entry in diary_read_result["entries"])
    assert "elapsed_ms" in diary_read_result

    empty_diary_result = mcp_server.tool_fast_diary_read("nobody")
    assert empty_diary_result["backend"] == "skeleton"
    assert empty_diary_result["agent"] == "nobody"
    assert empty_diary_result["entries"] == []
    assert empty_diary_result["message"] == "No diary entries yet."
    assert "elapsed_ms" in empty_diary_result

    add_drawer_result = mcp_server.tool_fast_add_drawer("wing_test", "room_test", "hello world")
    assert add_drawer_result["backend"] == "skeleton"
    assert add_drawer_result["success"] is True
    assert "drawer_id" in add_drawer_result
    assert "elapsed_ms" in add_drawer_result

    delete_drawer_result = mcp_server.tool_fast_delete_drawer(add_drawer_result["drawer_id"])
    assert delete_drawer_result["backend"] == "skeleton"
    assert delete_drawer_result["success"] is True
    assert delete_drawer_result["drawer_id"] == add_drawer_result["drawer_id"]
    assert delete_drawer_result["result"] is True
    assert "elapsed_ms" in delete_drawer_result

    missing_delete_result = mcp_server.tool_fast_delete_drawer("missing-drawer")
    assert missing_delete_result["backend"] == "skeleton"
    assert missing_delete_result["success"] is True
    assert missing_delete_result["drawer_id"] == "missing-drawer"
    assert missing_delete_result["result"] is False
    assert "elapsed_ms" in missing_delete_result

    native_snapshot_result = mcp_server.tool_fast_summary_for("fast-native")
    assert native_snapshot_result["backend"] == "skeleton"
    assert native_snapshot_result["summary"]["name"] == "fast-native"

    native_nodes_result = mcp_server.tool_fast_skeleton_read("fast-native", "nodes")
    assert native_nodes_result["backend"] == "skeleton"
    assert native_nodes_result["success"] is True
    assert "remember this" in native_nodes_result["content"] or "works_on" in native_nodes_result["content"]

    native_neighbors_result = mcp_server.tool_fast_neighbors("fast-native", drawer_id=diary_write_result["entry_id"])
    assert native_neighbors_result["backend"] == "skeleton"
    assert "neighbors" in native_neighbors_result
    assert "elapsed_ms" in native_neighbors_result

    merged_search_result = mcp_server.tool_fast_search("remember", limit=10)
    assert any(result.get("record_type") == "diary" for result in merged_search_result["results"])

    merged_duplicate_result = mcp_server.tool_fast_check_duplicate("remember this")
    assert merged_duplicate_result["backend"] == "skeleton"
    assert merged_duplicate_result["is_duplicate"] is True
    assert all(match["similarity"] >= merged_duplicate_result["threshold"] for match in merged_duplicate_result["matches"])

    snapshots_result = mcp_server.tool_fast_list_snapshots()
    assert "fast-native" in snapshots_result["snapshots"]

    index_result = mcp_server.tool_fast_skeleton_index()
    assert "fast-native" in index_result["snapshots"]
    assert index_result["exists"] is True


def test_fast_core_shapes_track_legacy_shapes(tmp_path, monkeypatch):
    snapshot = tmp_path / "session.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track autosave skeleton work for mempalace/autosave.py"}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-parity",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    legacy_status = mcp_server.tool_status()
    fast_status = mcp_server.tool_fast_status()
    assert set(legacy_status.keys()).issubset(set(fast_status.keys()))
    assert fast_status["protocol"] == legacy_status["protocol"]
    assert fast_status["aaak_dialect"] == legacy_status["aaak_dialect"]

    legacy_taxonomy = mcp_server.tool_get_taxonomy()
    fast_taxonomy = mcp_server.tool_fast_get_taxonomy()
    assert set(legacy_taxonomy.keys()).issubset(set(fast_taxonomy.keys()))

    legacy_list_wings = mcp_server.tool_list_wings()
    fast_list_wings = mcp_server.tool_fast_list_wings()
    assert set(legacy_list_wings.keys()).issubset(set(fast_list_wings.keys()))

    legacy_list_rooms = mcp_server.tool_list_rooms()
    fast_list_rooms = mcp_server.tool_fast_list_rooms()
    assert set(legacy_list_rooms.keys()).issubset(set(fast_list_rooms.keys()))

    legacy_duplicate = mcp_server.tool_check_duplicate("We should keep a relationship skeleton for mempalace/autosave.py.")
    fast_duplicate = mcp_server.tool_fast_check_duplicate("We should keep a relationship skeleton for mempalace/autosave.py.")
    assert set(legacy_duplicate.keys()).issubset(set(fast_duplicate.keys()))
    assert all(match["similarity"] >= fast_duplicate["threshold"] for match in fast_duplicate["matches"])

    legacy_search = mcp_server.tool_search("autosave", 5)
    fast_search = mcp_server.tool_fast_search("autosave", 5)
    assert {"query", "filters", "results"}.issubset(set(fast_search.keys()))
    assert "palace_path" in fast_search["filters"]
    if fast_search["results"]:
        assert {"text", "wing", "room", "source_file", "similarity", "local_score", "score_kind", "drawer_id"}.issubset(set(fast_search["results"][0].keys()))

    legacy_diary_empty = mcp_server.tool_diary_read("ghost")
    fast_diary_empty = mcp_server.tool_fast_diary_read("ghost")
    assert set(legacy_diary_empty.keys()).issubset(set(fast_diary_empty.keys()))

    legacy_kg_query = mcp_server.tool_kg_query("ghost")
    fast_kg_query = mcp_server.tool_fast_kg_query("ghost")
    assert set(legacy_kg_query.keys()).issubset(set(fast_kg_query.keys()))

    legacy_kg_add = mcp_server.tool_kg_add("Bob", "knows", "Carol")
    fast_kg_add = mcp_server.tool_fast_kg_add("Bob", "knows", "Carol")
    assert set(legacy_kg_add.keys()).issubset(set(fast_kg_add.keys()))
    assert fast_kg_add["fact"] == legacy_kg_add["fact"]

    legacy_kg_invalidate = mcp_server.tool_kg_invalidate("Bob", "knows", "Carol", ended="2026-04-08")
    fast_kg_invalidate = mcp_server.tool_fast_kg_invalidate("Bob", "knows", "Carol", ended="2026-04-08")
    assert set(legacy_kg_invalidate.keys()).issubset(set(fast_kg_invalidate.keys()))
    assert fast_kg_invalidate["fact"] == legacy_kg_invalidate["fact"]

    legacy_kg_timeline = mcp_server.tool_kg_timeline()
    fast_kg_timeline = mcp_server.tool_fast_kg_timeline()
    assert set(legacy_kg_timeline.keys()).issubset(set(fast_kg_timeline.keys()))

    legacy_kg_stats = mcp_server.tool_kg_stats()
    fast_kg_stats = mcp_server.tool_fast_kg_stats()
    assert set(legacy_kg_stats.keys()).issubset(set(fast_kg_stats.keys()))


    legacy_graph_stats = mcp_server.tool_graph_stats()
    fast_graph_stats = mcp_server.tool_fast_graph_stats()
    assert {"elapsed_ms", "backend"}.issubset(set(fast_graph_stats.keys()))
    assert {"memory_count", "wing_count", "room_count", "edge_count"}.issubset(set(fast_graph_stats.keys()))
    assert legacy_graph_stats["total_rooms"] >= 0

    legacy_tunnels = mcp_server.tool_find_tunnels()
    fast_tunnels = mcp_server.tool_fast_find_tunnels()
    assert {"tunnels", "elapsed_ms", "backend"}.issubset(set(fast_tunnels.keys()))
    assert isinstance(legacy_tunnels, list)
    assert isinstance(fast_tunnels["tunnels"], list)


def test_fast_search_and_duplicate_threshold_behavior(tmp_path, monkeypatch):
    snapshot = tmp_path / "session_search.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track autosave skeleton work for mempalace/autosave.py and benchmark search."}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-search",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    mcp_server.tool_fast_add_drawer("wing_test", "room_test", "autosave benchmark payload")
    mcp_server.tool_fast_add_drawer("wing_test", "room_test", "autosave benchmark payload with extension")
    mcp_server.tool_fast_diary_write("tester", "autosave benchmark payload", topic="general")

    fast_search = mcp_server.tool_fast_search("mempalace/autosave.py", 10)
    assert fast_search["backend"] == "skeleton"
    assert "palace_path" in fast_search["filters"]
    assert fast_search["results"]
    assert all("text" in result for result in fast_search["results"])
    assert all("source_file" in result for result in fast_search["results"])
    assert all("drawer_id" in result for result in fast_search["results"])
    assert fast_search["results"][0]["score_breakdown"]["file_hits"] >= fast_search["results"][0]["score_breakdown"].get("file_hits", 0)

    exact_duplicate = mcp_server.tool_fast_check_duplicate("autosave benchmark payload", threshold=1.0)
    assert exact_duplicate["backend"] == "skeleton"
    assert exact_duplicate["is_duplicate"] is True
    assert exact_duplicate["matches"]
    assert all(match["similarity"] >= 1.0 for match in exact_duplicate["matches"])
    exact_ids = [match["id"] for match in exact_duplicate["matches"]]
    assert len(exact_ids) == len(set(exact_ids))

    partial_duplicate = mcp_server.tool_fast_check_duplicate("autosave benchmark payload", threshold=0.5)
    assert partial_duplicate["backend"] == "skeleton"
    assert partial_duplicate["is_duplicate"] is True
    assert partial_duplicate["matches"]
    assert all(match["similarity"] >= 0.5 for match in partial_duplicate["matches"])
    assert any(match["similarity"] < 1.0 for match in partial_duplicate["matches"])





def test_fast_search_prefers_direct_file_hits_over_native_records(tmp_path, monkeypatch):
    snapshot = tmp_path / "session_mixed_search.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track autosave skeleton work for mempalace/autosave.py and benchmark search ordering."}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-mixed-search",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    mcp_server.tool_fast_add_drawer("wing_test", "room_test", "autosave benchmark ordering note")
    mcp_server.tool_fast_diary_write("tester", "autosave benchmark ordering note", topic="general")

    fast_search = mcp_server.tool_fast_search("mempalace/autosave.py", 10)
    assert fast_search["backend"] == "skeleton"
    assert fast_search["results"]

    top_result = fast_search["results"][0]
    assert top_result["record_type"] == "snapshot"
    assert top_result["score_breakdown"]["file_hits"] >= 1
    assert top_result["score_kind"] == "local_rule_score"
    assert "mempalace/autosave.py" in top_result.get("files", [])
    assert all(result.get("record_type") == "snapshot" for result in fast_search["results"])


def test_fast_duplicate_ranks_exact_before_substring_before_token_overlap(tmp_path, monkeypatch):
    snapshot = tmp_path / "session_duplicate_order.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track duplicate ranking for autosave benchmark payload ordering."}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-duplicate-order",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    exact = mcp_server.tool_fast_add_drawer("wing_test", "room_exact", "autosave benchmark payload")
    substring = mcp_server.tool_fast_add_drawer("wing_test", "room_substring", "autosave benchmark payload with extension")
    token_overlap = mcp_server.tool_fast_add_drawer("wing_test", "room_overlap", "autosave payload benchmark variant")

    assert exact["success"] is True
    assert substring["success"] is True
    assert token_overlap["success"] is True

    duplicate_result = mcp_server.tool_fast_check_duplicate("autosave benchmark payload", threshold=0.3)
    assert duplicate_result["backend"] == "skeleton"
    assert duplicate_result["is_duplicate"] is True
    assert len(duplicate_result["matches"]) >= 3

    similarities = [match["similarity"] for match in duplicate_result["matches"][:3]]
    assert similarities == sorted(similarities, reverse=True)
    assert duplicate_result["matches"][0]["content"] == "autosave benchmark payload"
    assert duplicate_result["matches"][0]["similarity"] == 1.0
    assert duplicate_result["matches"][1]["similarity"] < duplicate_result["matches"][0]["similarity"]
    assert duplicate_result["matches"][1]["similarity"] > duplicate_result["matches"][2]["similarity"]

    snapshot = tmp_path / "session_native_edges.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track fast native parity edge cases for diary and knowledge graph."}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-native-edges",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    first_drawer = mcp_server.tool_fast_add_drawer("wing_alpha", "room_one", "stable duplicate payload")
    duplicate_drawer = mcp_server.tool_fast_add_drawer("wing_alpha", "room_one", "stable duplicate payload")
    assert first_drawer["success"] is True
    assert duplicate_drawer["success"] is False
    assert duplicate_drawer["reason"] == "duplicate"
    assert duplicate_drawer["matches"][0]["similarity"] >= 1.0

    first_diary = mcp_server.tool_fast_diary_write("tester", "first entry", topic="general")
    second_diary = mcp_server.tool_fast_diary_write("tester", "second entry", topic="general")
    diary_read = mcp_server.tool_fast_diary_read("tester", last_n=2)
    assert diary_read["backend"] == "skeleton"
    assert diary_read["total"] >= 2
    assert diary_read["showing"] == 2
    assert diary_read["entries"][0]["timestamp"] >= diary_read["entries"][1]["timestamp"]
    assert {entry["content"] for entry in diary_read["entries"]} >= {"first entry", "second entry"}

    kg_added = mcp_server.tool_fast_kg_add("Alice", "knows", "Bob", valid_from="2026-04-08", source_closet="hall_facts")
    kg_deduped = mcp_server.tool_fast_kg_add("Alice", "knows", "Bob", valid_from="2026-04-08", source_closet="hall_facts")
    assert kg_added["success"] is True
    assert kg_deduped["success"] is True
    assert kg_deduped["deduplicated"] is True
    assert kg_deduped["triple_id"] == kg_added["triple_id"]

    kg_before_invalidate = mcp_server.tool_fast_kg_query("Alice")
    assert kg_before_invalidate["count"] >= 1
    assert any(fact["current"] is True for fact in kg_before_invalidate["facts"])

    kg_invalidated = mcp_server.tool_fast_kg_invalidate("Alice", "knows", "Bob", ended="2026-04-09")
    assert kg_invalidated["success"] is True
    assert kg_invalidated["updated"] >= 1
    assert kg_invalidated["ended"] == "2026-04-09"

    kg_after_invalidate = mcp_server.tool_fast_kg_query("Alice")
    assert any(fact["current"] is False for fact in kg_after_invalidate["facts"])
    assert any(fact["valid_to"] == "2026-04-09" for fact in kg_after_invalidate["facts"])

    kg_stats = mcp_server.tool_fast_kg_stats()
    assert kg_stats["backend"] == "skeleton"
    assert kg_stats["triples"] >= 1
    assert kg_stats["expired_facts"] >= 1
    assert "knows" in kg_stats["relationship_types"]

    kg_timeline = mcp_server.tool_fast_kg_timeline("Alice")
    assert kg_timeline["backend"] == "skeleton"
    assert kg_timeline["count"] >= 1
    assert any(item["valid_to"] == "2026-04-09" for item in kg_timeline["timeline"])



def test_fast_graph_and_tunnel_family_return_structured_projection_data(tmp_path, monkeypatch):
    snapshot = tmp_path / "session_graph.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track autosave skeleton work for mempalace/autosave.py and graph parity."}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-graph",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    mcp_server.tool_fast_add_drawer("wing_alpha", "room_shared", "alpha payload")
    mcp_server.tool_fast_add_drawer("wing_beta", "room_shared", "beta payload")
    mcp_server.tool_fast_add_drawer("wing_alpha", "room_unique", "unique payload")

    graph_result = mcp_server.tool_fast_graph_stats()
    assert graph_result["backend"] == "skeleton"
    assert graph_result["memory_count"] >= 1
    assert graph_result["wing_count"] >= 1
    assert graph_result["room_count"] >= 1
    assert graph_result["edge_count"] >= 0
    assert graph_result["total_rooms"] >= 1
    assert graph_result["tunnel_rooms"] >= 0
    assert graph_result["graph_model"] == "shared-room projection"
    assert graph_result["edge_model"] == "rooms connect when they appear under the same wing"
    assert isinstance(graph_result["rooms_per_wing"], dict)
    assert isinstance(graph_result["top_tunnels"], list)
    assert "elapsed_ms" in graph_result

    tunnels_result = mcp_server.tool_fast_find_tunnels("wing_alpha", "wing_beta")
    assert tunnels_result["backend"] == "skeleton"
    assert tunnels_result["wing_a"] == "wing_alpha"
    assert tunnels_result["wing_b"] == "wing_beta"
    assert tunnels_result["graph_model"] == "shared-room projection"
    assert isinstance(tunnels_result["tunnels"], list)
    assert any(tunnel["room"] == "room_shared" for tunnel in tunnels_result["tunnels"])
    assert all("count" in tunnel for tunnel in tunnels_result["tunnels"])
    assert all("recent" in tunnel for tunnel in tunnels_result["tunnels"])

    traverse_result = mcp_server.tool_fast_traverse("room_shared", max_hops=2)
    assert traverse_result["backend"] == "skeleton"
    assert traverse_result["start_room"] == "room_shared"
    assert traverse_result["max_hops"] == 2
    assert traverse_result["graph_model"] == "shared-room projection"
    assert isinstance(traverse_result["paths"], list)
    assert "results" in traverse_result
    assert traverse_result["results"][0]["room"] == "room_shared"
    assert traverse_result["results"][0]["hop"] == 0
    assert "elapsed_ms" in traverse_result

    missing_traverse = mcp_server.tool_fast_traverse("missing_room", max_hops=2)
    assert missing_traverse["backend"] == "skeleton"
    assert "error" in missing_traverse
    assert "suggestions" in missing_traverse

    snapshot = tmp_path / "session_search.jsonl"
    snapshot.write_text(
        '{"message": {"role": "user", "content": "Track autosave skeleton work for mempalace/autosave.py and benchmark search."}}\n'
        '{"message": {"role": "assistant", "content": "Done"}}\n',
        encoding="utf-8",
    )

    captured = []
    _patch_store(monkeypatch, captured)
    _patch_memories(monkeypatch, _sample_memories())
    monkeypatch.setattr("mempalace.autosave._git_repo_root", lambda workspace_root: None)

    persist_autosave(
        snapshot_file=str(snapshot),
        wing="wing_test",
        agent="tester",
        workspace_root=str(tmp_path),
        trigger="stop",
        session_id="session-search",
    )

    monkeypatch.chdir(tmp_path)

    import mempalace.mcp_server as mcp_server

    importlib.reload(mcp_server)

    mcp_server.tool_fast_add_drawer("wing_test", "room_test", "autosave benchmark payload")
    mcp_server.tool_fast_diary_write("tester", "autosave benchmark payload", topic="general")

    fast_search = mcp_server.tool_fast_search("autosave", 10)
    assert fast_search["backend"] == "skeleton"
    assert "palace_path" in fast_search["filters"]
    assert fast_search["results"]
    assert all("text" in result for result in fast_search["results"])
    assert all("source_file" in result for result in fast_search["results"])
    assert all("drawer_id" in result for result in fast_search["results"])
    assert all("local_score" in result for result in fast_search["results"])
    assert all(result["score_kind"] == "local_rule_score" for result in fast_search["results"])

    duplicate_result = mcp_server.tool_fast_check_duplicate("autosave benchmark payload", threshold=1.0)
    assert duplicate_result["backend"] == "skeleton"
    assert duplicate_result["is_duplicate"] is True
    assert duplicate_result["matches"]
    assert all(match["similarity"] >= 1.0 for match in duplicate_result["matches"])
    ids = [match["id"] for match in duplicate_result["matches"]]
    assert len(ids) == len(set(ids))

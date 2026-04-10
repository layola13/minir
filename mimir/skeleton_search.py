from __future__ import annotations

import ast
import hashlib
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from mimir.conversation_skeleton import _extract_tokens, index_output_path, skeleton_output_path

_MODULE_CACHE: dict[tuple[str, int, int], ast.Module | None] = {}
_LITERAL_CACHE: dict[tuple[str, int, int, str], object] = {}
_CONSTRUCTOR_LIST_CACHE: dict[tuple[str, int, int, str], List[dict]] = {}
_SNAPSHOT_RECORD_CACHE: dict[tuple[str, str], List[dict]] = {}
_ALL_RECORDS_CACHE: dict[tuple[str, tuple[str, ...], int], List[dict]] = {}
_GRAPH_COUNTS_CACHE: dict[tuple[str, str], dict] = {}

FAST_NATIVE_PACKAGE = "fast_native"
FAST_NATIVE_SNAPSHOT = "fast-native"


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


# ---------------------------------------------------------------------------
# Generic AST readers for Python skeleton modules
# ---------------------------------------------------------------------------


def _path_cache_key(file_path: Path) -> tuple[str, int, int] | None:
    try:
        stat = file_path.stat()
    except FileNotFoundError:
        return None
    return (str(file_path), stat.st_mtime_ns, stat.st_size)



def _parse_module(file_path: Path) -> ast.Module | None:
    cache_key = _path_cache_key(file_path)
    if cache_key is None:
        return None
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]
    try:
        parsed = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        parsed = None
    _MODULE_CACHE[cache_key] = parsed
    return parsed



def _read_literal_assignment(file_path: Path, name: str, fallback):
    path_key = _path_cache_key(file_path)
    if path_key is None:
        return fallback
    cache_key = (*path_key, name)
    if cache_key in _LITERAL_CACHE:
        return _LITERAL_CACHE[cache_key]
    module = _parse_module(file_path)
    if module is None:
        return fallback
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    return fallback
                _LITERAL_CACHE[cache_key] = value
                return value
    return fallback



def _read_constructor_list(file_path: Path, name: str) -> List[dict]:
    path_key = _path_cache_key(file_path)
    if path_key is None:
        return []
    cache_key = (*path_key, name)
    if cache_key in _CONSTRUCTOR_LIST_CACHE:
        return list(_CONSTRUCTOR_LIST_CACHE[cache_key])
    module = _parse_module(file_path)
    if module is None:
        return []
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id != name:
                continue
            if not isinstance(node.value, ast.List):
                return []
            items: List[dict] = []
            for element in node.value.elts:
                if not isinstance(element, ast.Call):
                    continue
                payload = {}
                for keyword in element.keywords:
                    try:
                        payload[str(keyword.arg)] = ast.literal_eval(keyword.value)
                    except (ValueError, SyntaxError):
                        payload = {}
                        break
                if payload:
                    items.append(payload)
            _CONSTRUCTOR_LIST_CACHE[cache_key] = list(items)
            return items
    return []


# ---------------------------------------------------------------------------
# Existing snapshot skeleton readers
# ---------------------------------------------------------------------------


def _snapshot_dir(workspace_root: str, snapshot: str) -> Path:
    root = skeleton_output_path(workspace_root)
    preferred = root / "snapshots" / snapshot
    if preferred.exists():
        return preferred
    legacy = root / snapshot
    return legacy



def _index_path(workspace_root: str) -> Path:
    return index_output_path(workspace_root)



def _load_index_summary(workspace_root: str) -> dict:
    index_path = _index_path(workspace_root)
    if not index_path.exists():
        return {
            "exists": False,
            "index_path": str(index_path),
            "snapshots": [],
            "snapshot_summaries": [],
            "global_top_topics": [],
            "global_top_files": [],
            "global_task_topics": [],
            "latest_snapshot": None,
            "snapshot_count": 0,
            "total_memory_count": 0,
            "index_text": "",
        }
    return {
        "exists": True,
        "index_path": str(index_path),
        "snapshots": _read_literal_assignment(index_path, "SNAPSHOTS", []),
        "snapshot_summaries": _read_literal_assignment(index_path, "SNAPSHOT_SUMMARIES", []),
        "global_top_topics": _read_literal_assignment(index_path, "GLOBAL_TOP_TOPICS", []),
        "global_top_files": _read_literal_assignment(index_path, "GLOBAL_TOP_FILES", []),
        "global_task_topics": _read_literal_assignment(index_path, "GLOBAL_TASK_TOPICS", []),
        "latest_snapshot": _read_literal_assignment(index_path, "LATEST_SNAPSHOT", None),
        "snapshot_count": _read_literal_assignment(index_path, "SNAPSHOT_COUNT", 0),
        "total_memory_count": _read_literal_assignment(index_path, "TOTAL_MEMORY_COUNT", 0),
        "index_text": index_path.read_text(encoding="utf-8"),
    }



def load_index(workspace_root: str) -> dict:
    start = time.perf_counter()
    result = _load_index_summary(workspace_root)
    result.update({"backend": "skeleton", "elapsed_ms": _elapsed_ms(start)})
    return result



def list_snapshots(workspace_root: str) -> dict:
    start = time.perf_counter()
    index_data = _load_index_summary(workspace_root)
    return {
        "backend": "skeleton",
        "snapshots": list(index_data["snapshots"]),
        "latest_snapshot": index_data["latest_snapshot"],
        "elapsed_ms": _elapsed_ms(start),
    }



def summary_for_snapshot(workspace_root: str, snapshot: str) -> dict:
    start = time.perf_counter()
    index_data = _load_index_summary(workspace_root)
    for summary in index_data["snapshot_summaries"]:
        if summary.get("name") == snapshot:
            return {
                "backend": "skeleton",
                "summary": dict(summary),
                "elapsed_ms": _elapsed_ms(start),
            }
    return {
        "backend": "skeleton",
        "error": f"Snapshot not found: {snapshot}",
        "snapshot": snapshot,
        "elapsed_ms": _elapsed_ms(start),
    }



def read_snapshot_module(workspace_root: str, snapshot: str, module: str) -> dict:
    start = time.perf_counter()
    allowed_modules = {"__init__", "summary", "nodes", "topics", "files", "patterns", "edges"}
    if module not in allowed_modules:
        return {
            "backend": "skeleton",
            "success": False,
            "error": f"Unsupported module: {module}",
            "allowed_modules": sorted(allowed_modules),
            "elapsed_ms": _elapsed_ms(start),
        }

    snapshot_dir = _snapshot_dir(workspace_root, snapshot)
    file_name = "__init__.py" if module == "__init__" else f"{module}.py"
    file_path = snapshot_dir / file_name
    if not file_path.exists():
        return {
            "backend": "skeleton",
            "success": False,
            "error": f"Module file not found: {file_name}",
            "snapshot": snapshot,
            "module": module,
            "file_path": str(file_path),
            "elapsed_ms": _elapsed_ms(start),
        }
    return {
        "backend": "skeleton",
        "success": True,
        "snapshot": snapshot,
        "module": module,
        "file_path": str(file_path),
        "content": file_path.read_text(encoding="utf-8"),
        "elapsed_ms": _elapsed_ms(start),
    }



def _parse_nodes(snapshot_dir: Path) -> List[dict]:
    return _read_constructor_list(snapshot_dir / "nodes.py", "NODES")



def _parse_topic_clusters(snapshot_dir: Path) -> List[dict]:
    return _read_constructor_list(snapshot_dir / "topics.py", "TOPIC_CLUSTERS")



def _parse_file_references(snapshot_dir: Path) -> List[dict]:
    return _read_constructor_list(snapshot_dir / "files.py", "FILE_REFERENCES")



def _parse_hard_edges(snapshot_dir: Path) -> List[dict]:
    return _read_literal_assignment(snapshot_dir / "edges.py", "hard_edges", [])



def _snapshot_records(workspace_root: str, snapshot: str) -> List[dict]:
    cache_key = (workspace_root, snapshot)
    if cache_key in _SNAPSHOT_RECORD_CACHE:
        return list(_SNAPSHOT_RECORD_CACHE[cache_key])
    summary = summary_for_snapshot(workspace_root, snapshot)
    if summary.get("error"):
        return []
    summary_data = summary.get("summary", {})
    task_description = str(summary_data.get("task_description", ""))
    task_topics = list(summary_data.get("task_topics", []))
    snapshot_dir = _snapshot_dir(workspace_root, snapshot)
    nodes = _parse_nodes(snapshot_dir)
    records = []
    for node in nodes:
        records.append(
            {
                "snapshot": snapshot,
                "index": node.get("index"),
                "memory_type": node.get("memory_type", "general"),
                "preview": node.get("preview", ""),
                "full_content": node.get("preview", ""),
                "topics": list(node.get("topics", [])),
                "files": list(node.get("files", [])),
                "task_description": task_description,
                "task_topics": task_topics,
                "wing": "conversation-skeleton",
                "room": f"nodes:{node.get('memory_type', 'general')}",
                "source_file": f"{snapshot}/nodes.py",
                "drawer_id": f"{snapshot}:{node.get('index')}",
                "record_type": "snapshot",
            }
        )
    _SNAPSHOT_RECORD_CACHE[cache_key] = list(records)
    return records


# ---------------------------------------------------------------------------
# Search scoring shared by both snapshot and native records
# ---------------------------------------------------------------------------


def _record_score(record: dict, query: str) -> dict:
    query_lower = query.lower()
    query_tokens = set(_extract_tokens(query))
    preview = str(record.get("preview", "")).lower()
    topics = [str(item).lower() for item in record.get("topics", [])]
    files = [str(item).lower() for item in record.get("files", [])]
    task_description = str(record.get("task_description", "")).lower()
    task_topics = [str(item).lower() for item in record.get("task_topics", [])]

    preview_hit = 1 if query_lower in preview else 0
    task_description_hit = 1 if query_lower in task_description else 0
    topic_hits = sum(1 for topic in topics if query_lower in topic)
    task_topic_hits = sum(1 for topic in task_topics if query_lower in topic)
    file_hits = sum(1 for path in files if query_lower in path)
    exact_type_hit = 1 if query_lower == str(record.get("memory_type", "")).lower() else 0

    preview_tokens = set(_extract_tokens(preview))
    task_description_tokens = set(_extract_tokens(task_description))
    topic_token_overlap = len(query_tokens.intersection(topics))
    task_token_overlap = len(query_tokens.intersection(task_topics))
    preview_token_overlap = len(query_tokens.intersection(preview_tokens))
    task_description_token_overlap = len(query_tokens.intersection(task_description_tokens))

    score = (
        preview_hit * 4
        + task_description_hit * 4
        + topic_hits * 3
        + task_topic_hits * 3
        + file_hits * 2
        + exact_type_hit * 2
        + topic_token_overlap * 2
        + task_token_overlap * 2
        + preview_token_overlap
        + task_description_token_overlap
    )

    return {
        "score": score,
        "preview_hit": preview_hit,
        "task_description_hit": task_description_hit,
        "topic_hits": topic_hits,
        "task_topic_hits": task_topic_hits,
        "file_hits": file_hits,
        "exact_type_hit": exact_type_hit,
        "topic_token_overlap": topic_token_overlap,
        "task_token_overlap": task_token_overlap,
        "preview_token_overlap": preview_token_overlap,
        "task_description_token_overlap": task_description_token_overlap,
    }



def _duplicate_similarity(content: str, candidate: str) -> float:
    left = content.strip().lower()
    right = candidate.strip().lower()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        shorter = min(len(left), len(right))
        longer = max(len(left), len(right))
        if longer == 0:
            return 0.0
        return round(shorter / longer, 3)
    left_tokens = set(_extract_tokens(left))
    right_tokens = set(_extract_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens.intersection(right_tokens))
    union = len(left_tokens.union(right_tokens))
    if union == 0:
        return 0.0
    return round(overlap / union, 3)



def _truncate_match_content(text: str) -> str:
    return text[:200] + "..." if len(text) > 200 else text


# ---------------------------------------------------------------------------
# Snapshot-only fast reads/searches
# ---------------------------------------------------------------------------


def _native_record_version(workspace_root: str) -> int:
    version = 0
    for file_path in _fast_native_files(workspace_root):
        try:
            stat = file_path.stat()
        except FileNotFoundError:
            continue
        version ^= stat.st_mtime_ns ^ stat.st_size
    return version



def _all_snapshot_records(workspace_root: str) -> List[dict]:
    index_data = _load_index_summary(workspace_root)
    snapshots = tuple(index_data["snapshots"])
    cache_key = (workspace_root, snapshots, 0)
    if cache_key in _ALL_RECORDS_CACHE:
        return list(_ALL_RECORDS_CACHE[cache_key])
    records: List[dict] = []
    for snapshot in snapshots:
        records.extend(_snapshot_records(workspace_root, snapshot))
    _ALL_RECORDS_CACHE[cache_key] = list(records)
    return records



def search_skeleton(
    workspace_root: str,
    query: str,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    limit: int = 5,
) -> dict:
    start = time.perf_counter()
    hits = []
    for record in _all_snapshot_records(workspace_root):
        if wing and record["wing"] != wing:
            continue
        if room and record["room"] != room:
            continue
        score = _record_score(record, query)
        if score["score"] <= 0:
            continue
        enriched = dict(record)
        enriched["text"] = record.get("full_content") or record.get("preview", "")
        enriched["source_file"] = Path(str(record.get("source_file", "?"))).name
        enriched["local_score"] = round(score["score"], 3)
        enriched["similarity"] = enriched["local_score"]
        enriched["score_kind"] = "local_rule_score"
        enriched["projection_kind"] = "snapshot_record"
        enriched["score_breakdown"] = {k: v for k, v in score.items() if k != "score"}
        hits.append(enriched)
    hits.sort(
        key=lambda item: (
            -item["local_score"],
            -item["score_breakdown"]["task_description_hit"],
            -item["score_breakdown"]["task_topic_hits"],
            -item["score_breakdown"]["topic_hits"],
            item["snapshot"],
            item["index"],
        )
    )
    return {
        "backend": "skeleton",
        "query": query,
        "filters": {"wing": wing, "room": room, "palace_path": str(skeleton_output_path(workspace_root))},
        "results": hits[:limit],
        "elapsed_ms": _elapsed_ms(start),
    }



def check_duplicate_skeleton(workspace_root: str, content: str, threshold: float = 0.9) -> dict:
    start = time.perf_counter()
    matches = []
    for record in _all_snapshot_records(workspace_root):
        preview = str(record.get("full_content") or record.get("preview", "")).strip()
        similarity = _duplicate_similarity(content, preview)
        if similarity < threshold:
            continue
        matches.append(
            {
                "id": record["drawer_id"],
                "wing": record["wing"],
                "room": record["room"],
                "similarity": similarity,
                "content": _truncate_match_content(preview),
                "snapshot": record["snapshot"],
            }
        )
    matches.sort(key=lambda item: (-float(item.get("similarity", 0.0)), str(item.get("wing", "")), str(item.get("room", "")), str(item.get("id", ""))))
    return {
        "backend": "skeleton",
        "is_duplicate": bool(matches),
        "matches": matches,
        "threshold": threshold,
        "elapsed_ms": _elapsed_ms(start),
    }



def get_taxonomy_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    room_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in _all_snapshot_records(workspace_root):
        room_counts[str(record["wing"])][str(record["room"])] += 1
    taxonomy = {wing: dict(sorted(rooms.items())) for wing, rooms in sorted(room_counts.items())}
    wings = {wing: sum(rooms.values()) for wing, rooms in sorted(room_counts.items())}
    rooms = Counter()
    for room_map in taxonomy.values():
        rooms.update(room_map)
    return {
        "backend": "skeleton",
        "taxonomy": taxonomy,
        "wings": wings,
        "rooms": dict(sorted(rooms.items())),
        "elapsed_ms": _elapsed_ms(start),
    }



def fast_status(workspace_root: str) -> dict:
    start = time.perf_counter()
    taxonomy = get_taxonomy_fast(workspace_root)
    index_data = _load_index_summary(workspace_root)
    return {
        "backend": "skeleton",
        "total_drawers": index_data["total_memory_count"],
        "wings": taxonomy["wings"],
        "rooms": taxonomy["rooms"],
        "palace_path": str(skeleton_output_path(workspace_root)),
        "elapsed_ms": _elapsed_ms(start),
    }



def list_wings_fast(workspace_root: str) -> dict:
    result = get_taxonomy_fast(workspace_root)
    return {"backend": "skeleton", "wings": result["wings"], "elapsed_ms": result["elapsed_ms"]}



def list_rooms_fast(workspace_root: str, wing: Optional[str] = None) -> dict:
    start = time.perf_counter()
    taxonomy = get_taxonomy_fast(workspace_root)["taxonomy"]
    if wing:
        rooms = dict(sorted(taxonomy.get(wing, {}).items()))
    else:
        counts = Counter()
        for room_map in taxonomy.values():
            counts.update(room_map)
        rooms = dict(sorted(counts.items()))
    return {
        "backend": "skeleton",
        "wing": wing or "all",
        "rooms": rooms,
        "elapsed_ms": _elapsed_ms(start),
    }



def _snapshot_graph_counts(workspace_root: str, snapshot: str) -> dict:
    cache_key = (workspace_root, snapshot)
    if cache_key in _GRAPH_COUNTS_CACHE:
        return dict(_GRAPH_COUNTS_CACHE[cache_key])
    snapshot_dir = _snapshot_dir(workspace_root, snapshot)
    counts = {
        "memory_count": len(_parse_nodes(snapshot_dir)),
        "topic_cluster_count": len(_parse_topic_clusters(snapshot_dir)),
        "file_group_count": len(_parse_file_references(snapshot_dir)),
        "edge_count": len(_parse_hard_edges(snapshot_dir)),
    }
    _GRAPH_COUNTS_CACHE[cache_key] = dict(counts)
    return counts



def _native_room_graph_nodes(workspace_root: str) -> dict[str, dict]:
    room_data: dict[str, dict] = defaultdict(lambda: {"wings": set(), "count": 0, "recent": ""})
    for record in _native_records(workspace_root):
        room = str(record.get("room", ""))
        wing = str(record.get("wing", ""))
        if not room or not wing or room == "general":
            continue
        room_data[room]["wings"].add(wing)
        room_data[room]["count"] += 1
        recent = str(record.get("filed_at") or record.get("timestamp") or record.get("valid_from") or "")
        if recent and recent > str(room_data[room].get("recent", "")):
            room_data[room]["recent"] = recent
    return room_data



def _snapshot_room_graph_nodes(workspace_root: str) -> dict[str, dict]:
    room_data: dict[str, dict] = defaultdict(lambda: {"wings": set(), "count": 0, "recent": ""})
    for record in _all_snapshot_records(workspace_root):
        room = str(record.get("room", ""))
        wing = str(record.get("wing", ""))
        if not room or not wing or room == "general":
            continue
        room_data[room]["wings"].add(wing)
        room_data[room]["count"] += 1
        snapshot = str(record.get("snapshot", ""))
        if snapshot and snapshot > str(room_data[room].get("recent", "")):
            room_data[room]["recent"] = snapshot
    return room_data



def _room_graph_stats_payload(room_data: dict[str, dict]) -> dict:
    tunnel_rooms = sum(1 for data in room_data.values() if len(data["wings"]) >= 2)
    wing_counts = Counter()
    total_edges = 0
    for room_name, data in room_data.items():
        wings = sorted(data["wings"])
        for wing in wings:
            wing_counts[wing] += 1
        if len(wings) >= 2:
            total_edges += (len(wings) * (len(wings) - 1)) // 2
    top_tunnels = [
        {
            "room": room_name,
            "wings": sorted(data["wings"]),
            "count": data["count"],
        }
        for room_name, data in sorted(room_data.items(), key=lambda item: (-len(item[1]["wings"]), -item[1]["count"], item[0]))
        if len(data["wings"]) >= 2
    ][:10]
    return {
        "total_rooms": len(room_data),
        "tunnel_rooms": tunnel_rooms,
        "total_edges": total_edges,
        "rooms_per_wing": dict(wing_counts.most_common()),
        "top_tunnels": top_tunnels,
        "graph_model": "shared-room projection",
        "edge_model": "rooms connect when they appear under the same wing",
    }



def _traverse_room_graph(room_data: dict[str, dict], start_room: str, max_hops: int) -> dict:
    if start_room not in room_data:
        suggestions = [room for room in sorted(room_data) if start_room.lower() in room.lower()][:5]
        return {"error": f"Room '{start_room}' not found", "suggestions": suggestions}

    visited = {start_room}
    results = [
        {
            "room": start_room,
            "wings": sorted(room_data[start_room]["wings"]),
            "halls": [],
            "count": room_data[start_room]["count"],
            "hop": 0,
        }
    ]

    frontier = [(start_room, 0)]
    while frontier:
        current_room, depth = frontier.pop(0)
        if depth >= max_hops:
            continue
        current_wings = set(room_data[current_room]["wings"])
        for room_name, data in sorted(room_data.items()):
            if room_name in visited:
                continue
            shared_wings = sorted(current_wings.intersection(data["wings"]))
            if not shared_wings:
                continue
            visited.add(room_name)
            results.append(
                {
                    "room": room_name,
                    "wings": sorted(data["wings"]),
                    "halls": [],
                    "count": data["count"],
                    "hop": depth + 1,
                    "connected_via": shared_wings,
                }
            )
            if depth + 1 < max_hops:
                frontier.append((room_name, depth + 1))

    results.sort(key=lambda item: (item["hop"], -item["count"], item["room"]))
    return {"results": results[:50]}



def _find_tunnels_payload(room_data: dict[str, dict], wing_a: Optional[str] = None, wing_b: Optional[str] = None) -> list[dict]:
    tunnels = []
    for room_name, data in room_data.items():
        wings = sorted(data["wings"])
        if len(wings) < 2:
            continue
        if wing_a and wing_a not in wings:
            continue
        if wing_b and wing_b not in wings:
            continue
        tunnels.append(
            {
                "room": room_name,
                "wings": wings,
                "halls": [],
                "count": data["count"],
                "recent": data.get("recent", ""),
            }
        )
    tunnels.sort(key=lambda item: (-item["count"], item["room"]))
    return tunnels[:50]





def graph_stats_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    room_data = _snapshot_room_graph_nodes(workspace_root)
    stats = _room_graph_stats_payload(room_data)
    stats.update(
        {
            "backend": "skeleton",
            "memory_count": int(_load_index_summary(workspace_root).get("total_memory_count", 0)),
            "wing_count": len({wing for data in room_data.values() for wing in data["wings"]}),
            "room_count": stats["total_rooms"],
            "edge_count": stats["total_edges"],
            "elapsed_ms": _elapsed_ms(start),
        }
    )
    return stats



def neighbors_fast(workspace_root: str, snapshot: str, node_index: int) -> dict:
    start = time.perf_counter()
    snapshot_dir = _snapshot_dir(workspace_root, snapshot)
    nodes = _parse_nodes(snapshot_dir)
    current = next((node for node in nodes if node.get("index") == node_index), None)
    if current is None:
        return {
            "backend": "skeleton",
            "snapshot": snapshot,
            "node_index": node_index,
            "neighbors": [],
            "error": f"Node not found: {node_index}",
            "elapsed_ms": _elapsed_ms(start),
        }
    neighbors = []
    current_topics = set(current.get("topics", []))
    current_files = set(current.get("files", []))
    for node in nodes:
        if node.get("index") == node_index:
            continue
        shared_topics = sorted(current_topics.intersection(node.get("topics", [])))
        shared_files = sorted(current_files.intersection(node.get("files", [])))
        if not shared_topics and not shared_files and current.get("memory_type") != node.get("memory_type"):
            continue
        relation = "same_type"
        if shared_topics:
            relation = "same_topic"
        elif shared_files:
            relation = "mentions_same_file"
        neighbors.append(
            {
                "index": node.get("index"),
                "memory_type": node.get("memory_type", "general"),
                "preview": node.get("preview", ""),
                "topics": shared_topics,
                "files": shared_files,
                "relation": relation,
            }
        )
    return {
        "backend": "skeleton",
        "snapshot": snapshot,
        "node_index": node_index,
        "neighbors": neighbors,
        "elapsed_ms": _elapsed_ms(start),
    }



def top_topics_fast(workspace_root: str, snapshot: Optional[str] = None) -> dict:
    start = time.perf_counter()
    counts = Counter()
    records = _snapshot_records(workspace_root, snapshot) if snapshot else _all_snapshot_records(workspace_root)
    for record in records:
        counts.update(record.get("topics", []))
    return {
        "backend": "skeleton",
        "topics": [{"topic": topic, "count": count} for topic, count in counts.most_common(10)],
        "elapsed_ms": _elapsed_ms(start),
    }



def top_files_fast(workspace_root: str, snapshot: Optional[str] = None) -> dict:
    start = time.perf_counter()
    counts = Counter()
    records = _snapshot_records(workspace_root, snapshot) if snapshot else _all_snapshot_records(workspace_root)
    for record in records:
        counts.update([path for path in record.get("files", []) if path])
    return {
        "backend": "skeleton",
        "files": [{"path": path, "count": count} for path, count in counts.most_common(10)],
        "elapsed_ms": _elapsed_ms(start),
    }



def traverse_fast(workspace_root: str, start_room: str, max_hops: int = 2) -> dict:
    start = time.perf_counter()
    traversal = _traverse_room_graph(_snapshot_room_graph_nodes(workspace_root), start_room, max_hops)
    traversal.update(
        {
            "backend": "skeleton",
            "start_room": start_room,
            "max_hops": max_hops,
            "graph_model": "shared-room projection",
            "paths": [
                {"from": item.get("connected_via", [start_room])[0] if item.get("connected_via") else start_room, "to": item["room"], "depth": item["hop"]}
                for item in traversal.get("results", [])
                if item.get("hop", 0) > 0
            ],
            "elapsed_ms": _elapsed_ms(start),
        }
    )
    return traversal



def find_tunnels_fast(workspace_root: str, wing_a: Optional[str] = None, wing_b: Optional[str] = None) -> dict:
    start = time.perf_counter()
    tunnels = _find_tunnels_payload(_snapshot_room_graph_nodes(workspace_root), wing_a=wing_a, wing_b=wing_b)
    return {
        "backend": "skeleton",
        "wing_a": wing_a,
        "wing_b": wing_b,
        "tunnels": tunnels,
        "graph_model": "shared-room projection",
        "elapsed_ms": _elapsed_ms(start),
    }


# ---------------------------------------------------------------------------
# fast_native Python skeleton package
# ---------------------------------------------------------------------------


def _fast_native_root(workspace_root: str) -> Path:
    return skeleton_output_path(workspace_root) / FAST_NATIVE_PACKAGE



def _fast_native_files(workspace_root: str) -> List[Path]:
    root = _fast_native_root(workspace_root)
    return [
        root / "__init__.py",
        root / "summary.py",
        root / "nodes.py",
        root / "topics.py",
        root / "files.py",
        root / "patterns.py",
        root / "edges.py",
        root / "drawers.py",
        root / "diary.py",
        root / "kg.py",
        root / "__index__.py",
    ]



def _quoted(value: str) -> str:
    return repr(value)



def _normalize_entity(value: str) -> str:
    return value.lower().replace(" ", "_").replace("'", "")



def _current_timestamp() -> str:
    return datetime.now().isoformat()



def _native_drawers(workspace_root: str) -> List[dict]:
    return _read_constructor_list(_fast_native_root(workspace_root) / "drawers.py", "DRAWERS")



def _native_diary_entries(workspace_root: str) -> List[dict]:
    return _read_constructor_list(_fast_native_root(workspace_root) / "diary.py", "DIARY_ENTRIES")



def _native_kg_triples(workspace_root: str) -> List[dict]:
    return _read_constructor_list(_fast_native_root(workspace_root) / "kg.py", "KG_TRIPLES")



def _topic_groups_from_records(records: List[dict]) -> List[dict]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, record in enumerate(records):
        for topic in record.get("topics", []):
            groups[str(topic)].append(idx)
    return [
        {"name": topic, "members": indexes}
        for topic, indexes in sorted(groups.items())
        if len(indexes) >= 2
    ]



def _file_groups_from_records(records: List[dict]) -> List[dict]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, record in enumerate(records):
        for path in record.get("files", []):
            if path:
                groups[str(path)].append(idx)
    return [
        {"path": path, "members": indexes}
        for path, indexes in sorted(groups.items())
        if len(indexes) >= 2
    ]



def _pattern_groups_from_records(records: List[dict]) -> List[dict]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for idx, record in enumerate(records):
        groups[str(record.get("memory_type", "general"))].append(idx)
    return [
        {"name": name, "members": indexes}
        for name, indexes in sorted(groups.items())
        if len(indexes) >= 2
    ]



def _co_occurrences_from_records(records: List[dict]) -> List[dict]:
    pair_counts: Dict[tuple[str, str], int] = defaultdict(int)
    for record in records:
        topics = sorted(set(str(topic) for topic in record.get("topics", [])))
        for idx, left in enumerate(topics):
            for right in topics[idx + 1 :]:
                pair_counts[(left, right)] += 1
    return [
        {"left": left, "right": right, "count": count}
        for (left, right), count in sorted(pair_counts.items())
        if count >= 2
    ]



def _hard_edges_from_records(records: List[dict]) -> List[dict]:
    edges = []
    for idx in range(len(records) - 1):
        left = records[idx]
        right = records[idx + 1]
        if left.get("room") == right.get("room") or left.get("wing") == right.get("wing"):
            edges.append(
                {
                    "source": idx,
                    "target": idx + 1,
                    "relation": "follows_from",
                    "label": None,
                }
            )
    return edges



def _native_records(workspace_root: str) -> List[dict]:
    version = _native_record_version(workspace_root)
    index_data = _load_index_summary(workspace_root)
    snapshots = tuple(index_data["snapshots"])
    cache_key = (workspace_root, snapshots, version)
    if cache_key in _ALL_RECORDS_CACHE:
        return list(_ALL_RECORDS_CACHE[cache_key])

    records: List[dict] = []
    for idx, item in enumerate(_native_drawers(workspace_root)):
        records.append(
            {
                "snapshot": FAST_NATIVE_SNAPSHOT,
                "index": idx,
                "memory_type": "drawer",
                "preview": str(item.get("content", ""))[:120],
                "full_content": str(item.get("content", "")),
                "topics": list(item.get("topics", [])),
                "files": [item.get("source_file", "")] if item.get("source_file") else [],
                "task_description": "",
                "task_topics": [],
                "wing": item.get("wing", "unknown"),
                "room": item.get("room", "unknown"),
                "source_file": item.get("source_file", ""),
                "drawer_id": item.get("drawer_id", ""),
                "filed_at": item.get("filed_at", ""),
                "added_by": item.get("added_by", ""),
                "record_type": "drawer",
            }
        )
    offset = len(records)
    for idx, item in enumerate(_native_diary_entries(workspace_root)):
        records.append(
            {
                "snapshot": FAST_NATIVE_SNAPSHOT,
                "index": offset + idx,
                "memory_type": "diary_entry",
                "preview": str(item.get("content", ""))[:120],
                "full_content": str(item.get("content", "")),
                "topics": _extract_tokens(str(item.get("content", "")))[:5],
                "files": [],
                "task_description": "",
                "task_topics": [],
                "wing": f"wing_{str(item.get('agent_name', '')).lower().replace(' ', '_')}",
                "room": "diary",
                "source_file": "",
                "drawer_id": item.get("entry_id", ""),
                "filed_at": item.get("timestamp", ""),
                "added_by": item.get("agent_name", ""),
                "record_type": "diary",
                "topic": item.get("topic", "general"),
            }
        )
    offset = len(records)
    for idx, triple in enumerate(_native_kg_triples(workspace_root)):
        text = f"{triple.get('subject', '')} {triple.get('predicate', '')} {triple.get('object', '')}".strip()
        records.append(
            {
                "snapshot": FAST_NATIVE_SNAPSHOT,
                "index": offset + idx,
                "memory_type": "kg_fact",
                "preview": text[:120],
                "full_content": text,
                "topics": _extract_tokens(text)[:5],
                "files": [],
                "task_description": "",
                "task_topics": [],
                "wing": "knowledge-graph",
                "room": f"predicate:{triple.get('predicate', '')}",
                "source_file": "",
                "drawer_id": triple.get("triple_id", ""),
                "filed_at": triple.get("extracted_at", ""),
                "added_by": "fast_native",
                "record_type": "kg",
            }
        )

    _ALL_RECORDS_CACHE[cache_key] = list(records)
    return records



def _native_index_text(summary: dict) -> str:
    lines = [
        "# __index__.py  (auto-generated fast native navigation bus)",
        "from __future__ import annotations",
        "",
        f"SNAPSHOTS = {[FAST_NATIVE_SNAPSHOT]!r}",
        f"LATEST_SNAPSHOT = {FAST_NATIVE_SNAPSHOT!r}",
        f"SNAPSHOT_SUMMARIES = {[summary]!r}",
        f"SNAPSHOT_COUNT = {1!r}",
        f"TOTAL_MEMORY_COUNT = {int(summary.get('memory_count', 0))!r}",
        f"GLOBAL_TOP_TOPICS = {list(summary.get('top_topics', []))!r}",
        f"GLOBAL_TOP_FILES = {list(summary.get('top_files', []))!r}",
        f"GLOBAL_TASK_TOPICS = {list(summary.get('task_topics', []))!r}",
        "",
        "def available_snapshots() -> list[str]:",
        "    return list(SNAPSHOTS)",
        "",
        "def latest_snapshot() -> str:",
        f"    return {FAST_NATIVE_SNAPSHOT!r}",
    ]
    return "\n".join(lines) + "\n"



def _write_fast_native_package(
    workspace_root: str,
    drawers: List[dict],
    diary_entries: List[dict],
    kg_triples: List[dict],
) -> None:
    root = _fast_native_root(workspace_root)
    root.mkdir(parents=True, exist_ok=True)

    records = []
    for drawer in drawers:
        records.append(
            {
                "memory_type": "drawer",
                "preview": str(drawer.get("content", ""))[:120],
                "topics": list(drawer.get("topics", [])),
                "files": [drawer.get("source_file", "")] if drawer.get("source_file") else [],
                "record_id": drawer.get("drawer_id", ""),
                "wing": drawer.get("wing", "unknown"),
                "room": drawer.get("room", "unknown"),
                "record_type": "drawer",
            }
        )
    for entry in diary_entries:
        records.append(
            {
                "memory_type": "diary_entry",
                "preview": str(entry.get("content", ""))[:120],
                "topics": _extract_tokens(str(entry.get("content", "")))[:5],
                "files": [],
                "record_id": entry.get("entry_id", ""),
                "wing": f"wing_{str(entry.get('agent_name', '')).lower().replace(' ', '_')}",
                "room": "diary",
                "record_type": "diary",
            }
        )
    for triple in kg_triples:
        text = f"{triple.get('subject', '')} {triple.get('predicate', '')} {triple.get('object', '')}".strip()
        records.append(
            {
                "memory_type": "kg_fact",
                "preview": text[:120],
                "topics": _extract_tokens(text)[:5],
                "files": [],
                "record_id": triple.get("triple_id", ""),
                "wing": "knowledge-graph",
                "room": f"predicate:{triple.get('predicate', '')}",
                "record_type": "kg",
            }
        )

    topic_groups = _topic_groups_from_records(records)
    file_groups = _file_groups_from_records(records)
    pattern_groups = _pattern_groups_from_records(records)
    co_occurrences = _co_occurrences_from_records(records)
    hard_edges = _hard_edges_from_records(records)

    topic_counts = Counter()
    file_counts = Counter()
    for record in records:
        topic_counts.update(record.get("topics", []))
        file_counts.update([path for path in record.get("files", []) if path])

    summary = {
        "name": FAST_NATIVE_SNAPSHOT,
        "summary_module": f"{FAST_NATIVE_PACKAGE}.summary",
        "nodes_module": f"{FAST_NATIVE_PACKAGE}.nodes",
        "edges_module": f"{FAST_NATIVE_PACKAGE}.edges",
        "memory_count": len(records),
        "task_description": "fast native python skeleton",
        "task_topics": ["fast", "native", "skeleton"],
        "top_topics": [topic for topic, _ in topic_counts.most_common(5)],
        "top_files": [path for path, _ in file_counts.most_common(5)],
        "drawer_count": len(drawers),
        "diary_entry_count": len(diary_entries),
        "kg_triple_count": len(kg_triples),
        "topic_cluster_count": len(topic_groups),
        "file_group_count": len(file_groups),
        "pattern_count": len(pattern_groups),
        "co_occurrence_count": len(co_occurrences),
        "edge_count": len(hard_edges),
    }

    init_text = "\n".join(
        [
            "from .summary import SNAPSHOT_NAME, TASK_DESCRIPTION, TASK_TOPICS, snapshot_overview",
            "from .nodes import MemoryNode, NODES",
            "from .topics import TopicCluster, TOPIC_CLUSTERS",
            "from .files import FileReference, FILE_REFERENCES",
            "from .patterns import PatternGroup, REPEATED_PATTERNS",
            "from .edges import RelationGraph",
            "from .drawers import DrawerRecord, DRAWERS",
            "from .diary import DiaryEntry, DIARY_ENTRIES",
            "from .kg import KGTriple, KG_TRIPLES",
            "",
            "graph = RelationGraph()",
            "",
        ]
    )

    summary_text = "\n".join(
        [
            "from __future__ import annotations",
            "",
            f"SNAPSHOT_NAME = {_quoted(FAST_NATIVE_SNAPSHOT)}",
            f"TASK_DESCRIPTION = {_quoted(summary['task_description'])}",
            f"TASK_TOPICS = {summary['task_topics']!r}",
            f"MEMORY_COUNT = {summary['memory_count']!r}",
            f"DRAWER_COUNT = {summary['drawer_count']!r}",
            f"DIARY_ENTRY_COUNT = {summary['diary_entry_count']!r}",
            f"KG_TRIPLE_COUNT = {summary['kg_triple_count']!r}",
            f"TOPIC_CLUSTER_COUNT = {summary['topic_cluster_count']!r}",
            f"FILE_GROUP_COUNT = {summary['file_group_count']!r}",
            f"PATTERN_COUNT = {summary['pattern_count']!r}",
            f"CO_OCCURRENCE_COUNT = {summary['co_occurrence_count']!r}",
            f"EDGE_COUNT = {summary['edge_count']!r}",
            f"TOP_TOPICS = {summary['top_topics']!r}",
            f"TOP_FILES = {summary['top_files']!r}",
            "",
            "def snapshot_overview() -> dict:",
            "    return {",
            "        'name': SNAPSHOT_NAME,",
            "        'task_description': TASK_DESCRIPTION,",
            "        'task_topics': list(TASK_TOPICS),",
            "        'memory_count': MEMORY_COUNT,",
            "        'drawer_count': DRAWER_COUNT,",
            "        'diary_entry_count': DIARY_ENTRY_COUNT,",
            "        'kg_triple_count': KG_TRIPLE_COUNT,",
            "        'top_topics': list(TOP_TOPICS),",
            "        'top_files': list(TOP_FILES),",
            "        'topic_cluster_count': TOPIC_CLUSTER_COUNT,",
            "        'file_group_count': FILE_GROUP_COUNT,",
            "        'pattern_count': PATTERN_COUNT,",
            "        'co_occurrence_count': CO_OCCURRENCE_COUNT,",
            "        'edge_count': EDGE_COUNT,",
            "    }",
            "",
        ]
    )

    nodes_lines = [
        "from __future__ import annotations",
        "",
        "class MemoryNode:",
        "    def __init__(self, index: int, memory_type: str, preview: str, topics: list[str], files: list[str], record_id: str, wing: str, room: str, record_type: str) -> None:",
        "        self.index = index",
        "        self.memory_type = memory_type",
        "        self.preview = preview",
        "        self.topics = topics",
        "        self.files = files",
        "        self.record_id = record_id",
        "        self.wing = wing",
        "        self.room = room",
        "        self.record_type = record_type",
        "",
        "NODES = [",
    ]
    for idx, record in enumerate(records):
        nodes_lines.append(
            f"    MemoryNode(index={idx!r}, memory_type={record['memory_type']!r}, preview={record['preview']!r}, topics={record['topics']!r}, files={record['files']!r}, record_id={record['record_id']!r}, wing={record['wing']!r}, room={record['room']!r}, record_type={record['record_type']!r}),"
        )
    nodes_lines.extend(["]", ""])
    nodes_text = "\n".join(nodes_lines)

    topics_lines = [
        "from __future__ import annotations",
        "",
        "class TopicCluster:",
        "    def __init__(self, name: str, members: list[int]) -> None:",
        "        self.name = name",
        "        self.members = members",
        "",
        "TOPIC_CLUSTERS = [",
    ]
    for group in topic_groups:
        topics_lines.append(f"    TopicCluster(name={group['name']!r}, members={group['members']!r}),")
    topics_lines.extend(["]", ""])
    topics_text = "\n".join(topics_lines)

    files_lines = [
        "from __future__ import annotations",
        "",
        "class FileReference:",
        "    def __init__(self, path: str, members: list[int]) -> None:",
        "        self.path = path",
        "        self.members = members",
        "",
        "FILE_REFERENCES = [",
    ]
    for group in file_groups:
        files_lines.append(f"    FileReference(path={group['path']!r}, members={group['members']!r}),")
    files_lines.extend(["]", ""])
    files_text = "\n".join(files_lines)

    patterns_lines = [
        "from __future__ import annotations",
        "",
        "class PatternGroup:",
        "    def __init__(self, name: str, members: list[int]) -> None:",
        "        self.name = name",
        "        self.members = members",
        "",
        "REPEATED_PATTERNS = [",
    ]
    for group in pattern_groups:
        patterns_lines.append(f"    PatternGroup(name={group['name']!r}, members={group['members']!r}),")
    patterns_lines.extend(["]", ""])
    patterns_text = "\n".join(patterns_lines)

    edges_text = "\n".join(
        [
            "from __future__ import annotations",
            "",
            "from mimir.topics import TOPIC_CLUSTERS",
            "from mimir.files import FILE_REFERENCES",
            "from mimir.patterns import REPEATED_PATTERNS",
            "",
            "class RelationGraph:",
            f"    memory_count = {len(records)!r}",
            "    topic_clusters = TOPIC_CLUSTERS",
            "    file_references = FILE_REFERENCES",
            "    repeated_patterns = REPEATED_PATTERNS",
            f"    co_occurrences = {co_occurrences!r}",
            f"    hard_edges = {hard_edges!r}",
            "",
            "    def neighbors(self, node_index: int) -> list[tuple[int, str]]:",
            "        neighbors: list[tuple[int, str]] = []",
            "        seen: set[tuple[int, str]] = set()",
            "        for cluster in self.topic_clusters:",
            "            if node_index not in cluster.members:",
            "                continue",
            "            for member in cluster.members:",
            "                if member == node_index:",
            "                    continue",
            "                item = (member, 'same_topic_as')",
            "                if item in seen:",
            "                    continue",
            "                seen.add(item)",
            "                neighbors.append(item)",
            "        for reference in self.file_references:",
            "            if node_index not in reference.members:",
            "                continue",
            "            for member in reference.members:",
            "                if member == node_index:",
            "                    continue",
            "                item = (member, 'mentions_same_file')",
            "                if item in seen:",
            "                    continue",
            "                seen.add(item)",
            "                neighbors.append(item)",
            "        for pattern in self.repeated_patterns:",
            "            if node_index not in pattern.members:",
            "                continue",
            "            for member in pattern.members:",
            "                if member == node_index:",
            "                    continue",
            "                item = (member, 'repeats_pattern')",
            "                if item in seen:",
            "                    continue",
            "                seen.add(item)",
            "                neighbors.append(item)",
            "        return neighbors",
            "",
        ]
    )

    drawers_lines = [
        "from __future__ import annotations",
        "",
        "class DrawerRecord:",
        "    def __init__(self, drawer_id: str, wing: str, room: str, content: str, source_file: str, added_by: str, filed_at: str, topics: list[str]) -> None:",
        "        self.drawer_id = drawer_id",
        "        self.wing = wing",
        "        self.room = room",
        "        self.content = content",
        "        self.source_file = source_file",
        "        self.added_by = added_by",
        "        self.filed_at = filed_at",
        "        self.topics = topics",
        "",
        "DRAWERS = [",
    ]
    for item in drawers:
        drawers_lines.append(
            f"    DrawerRecord(drawer_id={item['drawer_id']!r}, wing={item['wing']!r}, room={item['room']!r}, content={item['content']!r}, source_file={item['source_file']!r}, added_by={item['added_by']!r}, filed_at={item['filed_at']!r}, topics={item['topics']!r}),"
        )
    drawers_lines.extend(["]", ""])
    drawers_text = "\n".join(drawers_lines)

    diary_lines = [
        "from __future__ import annotations",
        "",
        "class DiaryEntry:",
        "    def __init__(self, entry_id: str, agent_name: str, topic: str, content: str, timestamp: str, date: str) -> None:",
        "        self.entry_id = entry_id",
        "        self.agent_name = agent_name",
        "        self.topic = topic",
        "        self.content = content",
        "        self.timestamp = timestamp",
        "        self.date = date",
        "",
        "DIARY_ENTRIES = [",
    ]
    for item in diary_entries:
        diary_lines.append(
            f"    DiaryEntry(entry_id={item['entry_id']!r}, agent_name={item['agent_name']!r}, topic={item['topic']!r}, content={item['content']!r}, timestamp={item['timestamp']!r}, date={item['date']!r}),"
        )
    diary_lines.extend(["]", ""])
    diary_text = "\n".join(diary_lines)

    kg_lines = [
        "from __future__ import annotations",
        "",
        "class KGTriple:",
        "    def __init__(self, triple_id: str, subject: str, subject_id: str, predicate: str, object: str, object_id: str, valid_from: str | None, valid_to: str | None, confidence: float, source_closet: str | None, extracted_at: str) -> None:",
        "        self.triple_id = triple_id",
        "        self.subject = subject",
        "        self.subject_id = subject_id",
        "        self.predicate = predicate",
        "        self.object = object",
        "        self.object_id = object_id",
        "        self.valid_from = valid_from",
        "        self.valid_to = valid_to",
        "        self.confidence = confidence",
        "        self.source_closet = source_closet",
        "        self.extracted_at = extracted_at",
        "",
        "KG_TRIPLES = [",
    ]
    for item in kg_triples:
        kg_lines.append(
            f"    KGTriple(triple_id={item['triple_id']!r}, subject={item['subject']!r}, subject_id={item['subject_id']!r}, predicate={item['predicate']!r}, object={item['object']!r}, object_id={item['object_id']!r}, valid_from={item['valid_from']!r}, valid_to={item['valid_to']!r}, confidence={item['confidence']!r}, source_closet={item['source_closet']!r}, extracted_at={item['extracted_at']!r}),"
        )
    kg_lines.extend(["]", ""])
    kg_text = "\n".join(kg_lines)

    (root / "__init__.py").write_text(init_text, encoding="utf-8")
    (root / "summary.py").write_text(summary_text, encoding="utf-8")
    (root / "nodes.py").write_text(nodes_text, encoding="utf-8")
    (root / "topics.py").write_text(topics_text, encoding="utf-8")
    (root / "files.py").write_text(files_text, encoding="utf-8")
    (root / "patterns.py").write_text(patterns_text, encoding="utf-8")
    (root / "edges.py").write_text(edges_text, encoding="utf-8")
    (root / "drawers.py").write_text(drawers_text, encoding="utf-8")
    (root / "diary.py").write_text(diary_text, encoding="utf-8")
    (root / "kg.py").write_text(kg_text, encoding="utf-8")
    (root / "__index__.py").write_text(_native_index_text(summary), encoding="utf-8")



def add_drawer_fast(
    workspace_root: str,
    wing: str,
    room: str,
    content: str,
    source_file: str = None,
    added_by: str = "claude",
) -> dict:
    start = time.perf_counter()
    content = content.strip()
    drawers = _native_drawers(workspace_root)
    for item in drawers:
        existing = str(item.get("content", "")).strip().lower()
        if existing == content.lower():
            match_content = str(item.get("content", ""))
            return {
                "backend": "skeleton",
                "success": False,
                "reason": "duplicate",
                "matches": [
                    {
                        "id": item.get("drawer_id", ""),
                        "wing": item.get("wing", wing),
                        "room": item.get("room", room),
                        "similarity": 1.0,
                        "content": match_content[:200] + "..." if len(match_content) > 200 else match_content,
                    }
                ],
                "elapsed_ms": _elapsed_ms(start),
            }
    filed_at = _current_timestamp()
    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((content + filed_at).encode()).hexdigest()[:16]}"
    drawers.append(
        {
            "drawer_id": drawer_id,
            "wing": wing,
            "room": room,
            "content": content,
            "source_file": source_file or "",
            "added_by": added_by,
            "filed_at": filed_at,
            "topics": _extract_tokens(content)[:5],
        }
    )
    _write_fast_native_package(workspace_root, drawers, _native_diary_entries(workspace_root), _native_kg_triples(workspace_root))
    refresh_fast_state()
    return {
        "backend": "skeleton",
        "success": True,
        "drawer_id": drawer_id,
        "wing": wing,
        "room": room,
        "elapsed_ms": _elapsed_ms(start),
    }



def delete_drawer_fast(workspace_root: str, drawer_id: str) -> dict:
    start = time.perf_counter()
    original_drawers = _native_drawers(workspace_root)
    drawers = [item for item in original_drawers if item.get("drawer_id") != drawer_id]
    if len(drawers) == len(original_drawers):
        return {
            "backend": "skeleton",
            "success": True,
            "drawer_id": drawer_id,
            "result": False,
            "elapsed_ms": _elapsed_ms(start),
        }
    _write_fast_native_package(workspace_root, drawers, _native_diary_entries(workspace_root), _native_kg_triples(workspace_root))
    refresh_fast_state()
    return {
        "backend": "skeleton",
        "success": True,
        "drawer_id": drawer_id,
        "result": True,
        "elapsed_ms": _elapsed_ms(start),
    }



def diary_write_fast(workspace_root: str, agent_name: str, entry: str, topic: str = "general") -> dict:
    start = time.perf_counter()
    diary_entries = _native_diary_entries(workspace_root)
    now = datetime.now()
    timestamp = now.isoformat()
    entry_id = f"diary_{agent_name.lower().replace(' ', '_')}_{now.strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(entry.encode()).hexdigest()[:8]}"
    diary_entries.append(
        {
            "entry_id": entry_id,
            "agent_name": agent_name,
            "topic": topic,
            "content": entry,
            "timestamp": timestamp,
            "date": now.strftime("%Y-%m-%d"),
        }
    )
    _write_fast_native_package(workspace_root, _native_drawers(workspace_root), diary_entries, _native_kg_triples(workspace_root))
    refresh_fast_state()
    return {
        "backend": "skeleton",
        "success": True,
        "entry_id": entry_id,
        "agent": agent_name,
        "topic": topic,
        "timestamp": timestamp,
        "elapsed_ms": _elapsed_ms(start),
    }



def diary_read_fast(workspace_root: str, agent_name: str, last_n: int = 10) -> dict:
    start = time.perf_counter()
    entries = [item for item in _native_diary_entries(workspace_root) if item.get("agent_name") == agent_name]
    if not entries:
        return {
            "backend": "skeleton",
            "agent": agent_name,
            "entries": [],
            "message": "No diary entries yet.",
            "elapsed_ms": _elapsed_ms(start),
        }
    entries.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    selected = entries[:last_n]
    return {
        "backend": "skeleton",
        "agent": agent_name,
        "entries": [
            {
                "date": item.get("date", ""),
                "timestamp": item.get("timestamp", ""),
                "topic": item.get("topic", ""),
                "content": item.get("content", ""),
            }
            for item in selected
        ],
        "total": len(entries),
        "showing": len(selected),
        "elapsed_ms": _elapsed_ms(start),
    }



def kg_add_fast(
    workspace_root: str,
    subject: str,
    predicate: str,
    object: str,
    valid_from: str = None,
    source_closet: str = None,
) -> dict:
    start = time.perf_counter()
    triples = _native_kg_triples(workspace_root)
    subject_id = _normalize_entity(subject)
    object_id = _normalize_entity(object)
    predicate_norm = predicate.lower().replace(" ", "_")
    for triple in triples:
        if (
            triple.get("subject_id") == subject_id
            and triple.get("predicate") == predicate_norm
            and triple.get("object_id") == object_id
            and triple.get("valid_to") is None
        ):
            return {
                "backend": "skeleton",
                "success": True,
                "triple_id": triple.get("triple_id"),
                "fact": f"{subject} → {predicate} → {object}",
                "deduplicated": True,
                "elapsed_ms": _elapsed_ms(start),
            }
    triple_id = f"t_{subject_id}_{predicate_norm}_{object_id}_{hashlib.md5(f'{valid_from}{_current_timestamp()}'.encode()).hexdigest()[:8]}"
    triples.append(
        {
            "triple_id": triple_id,
            "subject": subject,
            "subject_id": subject_id,
            "predicate": predicate_norm,
            "object": object,
            "object_id": object_id,
            "valid_from": valid_from,
            "valid_to": None,
            "confidence": 1.0,
            "source_closet": source_closet,
            "extracted_at": _current_timestamp(),
        }
    )
    _write_fast_native_package(workspace_root, _native_drawers(workspace_root), _native_diary_entries(workspace_root), triples)
    refresh_fast_state()
    return {
        "backend": "skeleton",
        "success": True,
        "triple_id": triple_id,
        "fact": f"{subject} → {predicate} → {object}",
        "elapsed_ms": _elapsed_ms(start),
    }



def kg_invalidate_fast(workspace_root: str, subject: str, predicate: str, object: str, ended: str = None) -> dict:
    start = time.perf_counter()
    triples = _native_kg_triples(workspace_root)
    subject_id = _normalize_entity(subject)
    object_id = _normalize_entity(object)
    predicate_norm = predicate.lower().replace(" ", "_")
    ended_value = ended or date.today().isoformat()
    updated = 0
    for triple in triples:
        if (
            triple.get("subject_id") == subject_id
            and triple.get("predicate") == predicate_norm
            and triple.get("object_id") == object_id
            and triple.get("valid_to") is None
        ):
            triple["valid_to"] = ended_value
            updated += 1
    _write_fast_native_package(workspace_root, _native_drawers(workspace_root), _native_diary_entries(workspace_root), triples)
    refresh_fast_state()
    return {
        "backend": "skeleton",
        "success": True,
        "fact": f"{subject} → {predicate} → {object}",
        "ended": ended_value,
        "updated": updated,
        "elapsed_ms": _elapsed_ms(start),
    }



def kg_query_fast(workspace_root: str, entity: str, as_of: str = None, direction: str = "both") -> dict:
    start = time.perf_counter()
    entity_id = _normalize_entity(entity)
    facts = []
    for triple in _native_kg_triples(workspace_root):
        valid_from = triple.get("valid_from")
        valid_to = triple.get("valid_to")
        if as_of:
            if valid_from and valid_from > as_of:
                continue
            if valid_to and valid_to < as_of:
                continue
        if direction in ("outgoing", "both") and triple.get("subject_id") == entity_id:
            facts.append(
                {
                    "direction": "outgoing",
                    "subject": triple.get("subject", entity),
                    "predicate": triple.get("predicate", ""),
                    "object": triple.get("object", ""),
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "confidence": triple.get("confidence", 1.0),
                    "source_closet": triple.get("source_closet"),
                    "current": valid_to is None,
                }
            )
        if direction in ("incoming", "both") and triple.get("object_id") == entity_id:
            facts.append(
                {
                    "direction": "incoming",
                    "subject": triple.get("subject", ""),
                    "predicate": triple.get("predicate", ""),
                    "object": triple.get("object", entity),
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                    "confidence": triple.get("confidence", 1.0),
                    "source_closet": triple.get("source_closet"),
                    "current": valid_to is None,
                }
            )
    return {
        "backend": "skeleton",
        "entity": entity,
        "as_of": as_of,
        "facts": facts,
        "count": len(facts),
        "elapsed_ms": _elapsed_ms(start),
    }



def kg_timeline_fast(workspace_root: str, entity: str = None) -> dict:
    start = time.perf_counter()
    entity_id = _normalize_entity(entity) if entity else None
    timeline = []
    for triple in _native_kg_triples(workspace_root):
        if entity_id and entity_id not in {triple.get("subject_id"), triple.get("object_id")}:
            continue
        timeline.append(
            {
                "subject": triple.get("subject", ""),
                "predicate": triple.get("predicate", ""),
                "object": triple.get("object", ""),
                "valid_from": triple.get("valid_from"),
                "valid_to": triple.get("valid_to"),
                "current": triple.get("valid_to") is None,
            }
        )
    timeline.sort(
        key=lambda item: (
            item.get("valid_from") is None,
            item.get("valid_from") or "",
            item["subject"],
            item["predicate"],
            item["object"],
        )
    )
    return {
        "backend": "skeleton",
        "entity": entity or "all",
        "timeline": timeline,
        "count": len(timeline),
        "elapsed_ms": _elapsed_ms(start),
    }



def kg_stats_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    triples = _native_kg_triples(workspace_root)
    current = sum(1 for triple in triples if triple.get("valid_to") is None)
    predicates = sorted({str(triple.get("predicate", "")) for triple in triples if triple.get("predicate")})
    entities = {str(triple.get("subject", "")) for triple in triples if triple.get("subject")} | {
        str(triple.get("object", "")) for triple in triples if triple.get("object")
    }
    return {
        "backend": "skeleton",
        "entities": len(entities),
        "triples": len(triples),
        "current_facts": current,
        "expired_facts": len(triples) - current,
        "relationship_types": predicates,
        "elapsed_ms": _elapsed_ms(start),
    }



def fast_root_status(workspace_root: str) -> dict:
    start = time.perf_counter()
    records = _native_records(workspace_root)
    wings = Counter()
    rooms = Counter()
    for record in records:
        wings[str(record.get("wing", "unknown"))] += 1
        rooms[str(record.get("room", "unknown"))] += 1
    return {
        "backend": "skeleton",
        "total_drawers": len(records),
        "wings": dict(sorted(wings.items())),
        "rooms": dict(sorted(rooms.items())),
        "palace_path": str(_fast_native_root(workspace_root)),
        "protocol": "fast_native_python_skeleton",
        "aaak_dialect": None,
        "elapsed_ms": _elapsed_ms(start),
    }



def list_wings_native(workspace_root: str) -> dict:
    result = fast_root_status(workspace_root)
    return {"backend": "skeleton", "wings": result["wings"], "elapsed_ms": result["elapsed_ms"]}



def list_rooms_native(workspace_root: str, wing: Optional[str] = None) -> dict:
    start = time.perf_counter()
    rooms = Counter()
    for record in _native_records(workspace_root):
        if wing and record.get("wing") != wing:
            continue
        rooms[str(record.get("room", "unknown"))] += 1
    return {
        "backend": "skeleton",
        "wing": wing or "all",
        "rooms": dict(sorted(rooms.items())),
        "elapsed_ms": _elapsed_ms(start),
    }



def taxonomy_native(workspace_root: str) -> dict:
    start = time.perf_counter()
    taxonomy: dict[str, dict[str, int]] = defaultdict(dict)
    for record in _native_records(workspace_root):
        wing = str(record.get("wing", "unknown"))
        room = str(record.get("room", "unknown"))
        taxonomy.setdefault(wing, {})
        taxonomy[wing][room] = taxonomy[wing].get(room, 0) + 1
    return {
        "backend": "skeleton",
        "taxonomy": {wing: dict(sorted(rooms.items())) for wing, rooms in sorted(taxonomy.items())},
        "wings": {wing: sum(rooms.values()) for wing, rooms in sorted(taxonomy.items())},
        "elapsed_ms": _elapsed_ms(start),
    }



def search_native(workspace_root: str, query: str, wing: Optional[str] = None, room: Optional[str] = None, limit: int = 5) -> dict:
    start = time.perf_counter()
    hits = []
    for record in _native_records(workspace_root):
        if wing and record.get("wing") != wing:
            continue
        if room and record.get("room") != room:
            continue
        score = _record_score(record, query)
        if score["score"] <= 0:
            continue
        enriched = dict(record)
        enriched["text"] = record.get("full_content") or record.get("preview", "")
        enriched["source_file"] = Path(str(record.get("source_file", "?"))).name
        enriched["local_score"] = round(score["score"], 3)
        enriched["similarity"] = enriched["local_score"]
        enriched["score_kind"] = "local_rule_score"
        enriched["projection_kind"] = "native_record"
        enriched["score_breakdown"] = {k: v for k, v in score.items() if k != "score"}
        hits.append(enriched)
    hits.sort(key=lambda item: (-item["local_score"], item.get("wing", ""), item.get("room", ""), item.get("drawer_id", "")))
    return {
        "backend": "skeleton",
        "query": query,
        "filters": {"wing": wing, "room": room, "palace_path": str(_fast_native_root(workspace_root))},
        "results": hits[:limit],
        "elapsed_ms": _elapsed_ms(start),
    }



def duplicate_native(workspace_root: str, content: str, threshold: float = 0.9) -> dict:
    start = time.perf_counter()
    matches = []
    for record in _native_records(workspace_root):
        body = str(record.get("full_content") or record.get("preview", "")).strip()
        similarity = _duplicate_similarity(content, body)
        if similarity < threshold:
            continue
        matches.append(
            {
                "id": record.get("drawer_id", ""),
                "wing": record.get("wing", "unknown"),
                "room": record.get("room", "unknown"),
                "similarity": similarity,
                "content": _truncate_match_content(body),
            }
        )
    matches.sort(key=lambda item: (-float(item.get("similarity", 0.0)), str(item.get("wing", "")), str(item.get("room", "")), str(item.get("id", ""))))
    return {
        "backend": "skeleton",
        "is_duplicate": bool(matches),
        "matches": matches,
        "threshold": threshold,
        "elapsed_ms": _elapsed_ms(start),
    }



def traverse_native(workspace_root: str, start_room: str, max_hops: int = 2) -> dict:
    start = time.perf_counter()
    room_graph: dict[str, set[str]] = defaultdict(set)
    wing_to_rooms: dict[str, set[str]] = defaultdict(set)
    for record in _native_records(workspace_root):
        wing_to_rooms[str(record.get("wing", "unknown"))].add(str(record.get("room", "unknown")))
    for rooms in wing_to_rooms.values():
        room_list = sorted(rooms)
        for left in room_list:
            for right in room_list:
                if left != right:
                    room_graph[left].add(right)
    visited = {start_room}
    frontier = [(start_room, 0)]
    paths = []
    while frontier:
        room, depth = frontier.pop(0)
        if depth >= max_hops:
            continue
        for neighbor in sorted(room_graph.get(room, set())):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            frontier.append((neighbor, depth + 1))
            paths.append({"from": room, "to": neighbor, "depth": depth + 1})
    return {
        "backend": "skeleton",
        "start_room": start_room,
        "max_hops": max_hops,
        "graph_model": "shared-room projection",
        "paths": paths,
        "elapsed_ms": _elapsed_ms(start),
    }



def find_tunnels_native(workspace_root: str, wing_a: Optional[str] = None, wing_b: Optional[str] = None) -> dict:
    start = time.perf_counter()
    taxonomy = taxonomy_native(workspace_root)["taxonomy"]
    if wing_a and wing_b:
        shared = sorted(set(taxonomy.get(wing_a, {})).intersection(taxonomy.get(wing_b, {})))
        tunnels = [{"room": room, "wings": [wing_a, wing_b]} for room in shared]
    else:
        room_to_wings: dict[str, set[str]] = defaultdict(set)
        for wing_name, rooms in taxonomy.items():
            for room_name in rooms:
                room_to_wings[room_name].add(wing_name)
        tunnels = [
            {"room": room_name, "wings": sorted(wings)}
            for room_name, wings in sorted(room_to_wings.items())
            if len(wings) >= 2
        ]
    return {
        "backend": "skeleton",
        "wing_a": wing_a,
        "wing_b": wing_b,
        "tunnels": tunnels,
        "graph_model": "shared-room projection",
        "elapsed_ms": _elapsed_ms(start),
    }



def graph_stats_native(workspace_root: str) -> dict:
    start = time.perf_counter()
    room_data = _native_room_graph_nodes(workspace_root)
    stats = _room_graph_stats_payload(room_data)
    stats.update(
        {
            "backend": "skeleton",
            "memory_count": len(_native_records(workspace_root)),
            "wing_count": len({wing for data in room_data.values() for wing in data["wings"]}),
            "room_count": stats["total_rooms"],
            "edge_count": stats["total_edges"],
            "elapsed_ms": _elapsed_ms(start),
        }
    )
    return stats



def top_topics_native(workspace_root: str) -> dict:
    start = time.perf_counter()
    counts = Counter()
    for record in _native_records(workspace_root):
        counts.update(record.get("topics", []))
    return {
        "backend": "skeleton",
        "topics": [{"topic": topic, "count": count} for topic, count in counts.most_common(10)],
        "elapsed_ms": _elapsed_ms(start),
    }



def top_files_native(workspace_root: str) -> dict:
    start = time.perf_counter()
    counts = Counter()
    for record in _native_records(workspace_root):
        counts.update([path for path in record.get("files", []) if path])
    return {
        "backend": "skeleton",
        "files": [{"path": path, "count": count} for path, count in counts.most_common(10)],
        "elapsed_ms": _elapsed_ms(start),
    }



def neighbors_native(workspace_root: str, drawer_id: str) -> dict:
    start = time.perf_counter()
    records = _native_records(workspace_root)
    current = next((record for record in records if record.get("drawer_id") == drawer_id), None)
    if current is None:
        return {
            "backend": "skeleton",
            "drawer_id": drawer_id,
            "neighbors": [],
            "error": f"Record not found: {drawer_id}",
            "elapsed_ms": _elapsed_ms(start),
        }
    neighbors = []
    for record in records:
        if record.get("drawer_id") == drawer_id:
            continue
        shared_topics = sorted(set(current.get("topics", [])).intersection(record.get("topics", [])))
        shared_files = sorted(set(current.get("files", [])).intersection(record.get("files", [])))
        if not shared_topics and not shared_files and current.get("wing") != record.get("wing"):
            continue
        relation = "same_wing"
        if shared_topics:
            relation = "same_topic"
        elif shared_files:
            relation = "mentions_same_file"
        neighbors.append(
            {
                "drawer_id": record.get("drawer_id", ""),
                "wing": record.get("wing", "unknown"),
                "room": record.get("room", "unknown"),
                "relation": relation,
                "topics": shared_topics,
                "files": shared_files,
                "preview": record.get("preview", ""),
            }
        )
    return {
        "backend": "skeleton",
        "drawer_id": drawer_id,
        "neighbors": neighbors,
        "elapsed_ms": _elapsed_ms(start),
    }



def list_native_records(workspace_root: str) -> dict:
    start = time.perf_counter()
    return {
        "backend": "skeleton",
        "records": _native_records(workspace_root),
        "elapsed_ms": _elapsed_ms(start),
    }



def summary_native(workspace_root: str) -> dict:
    start = time.perf_counter()
    summary_path = _fast_native_root(workspace_root) / "summary.py"
    summary = {
        "name": FAST_NATIVE_SNAPSHOT,
        "memory_count": _read_literal_assignment(summary_path, "MEMORY_COUNT", 0),
        "drawers": _read_literal_assignment(summary_path, "DRAWER_COUNT", 0),
        "diary_entries": _read_literal_assignment(summary_path, "DIARY_ENTRY_COUNT", 0),
        "kg_triples": _read_literal_assignment(summary_path, "KG_TRIPLE_COUNT", 0),
        "task_description": _read_literal_assignment(summary_path, "TASK_DESCRIPTION", "fast native python skeleton"),
        "task_topics": _read_literal_assignment(summary_path, "TASK_TOPICS", ["fast", "native", "skeleton"]),
        "top_topics": _read_literal_assignment(summary_path, "TOP_TOPICS", []),
        "top_files": _read_literal_assignment(summary_path, "TOP_FILES", []),
    }
    return {"backend": "skeleton", "summary": summary, "elapsed_ms": _elapsed_ms(start)}



def read_native_module(workspace_root: str, module: str) -> dict:
    start = time.perf_counter()
    allowed_modules = {"__init__", "summary", "nodes", "topics", "files", "patterns", "edges"}
    if module not in allowed_modules:
        return {
            "backend": "skeleton",
            "success": False,
            "error": f"Unsupported module: {module}",
            "allowed_modules": sorted(allowed_modules),
            "elapsed_ms": _elapsed_ms(start),
        }
    file_name = "__init__.py" if module == "__init__" else f"{module}.py"
    file_path = _fast_native_root(workspace_root) / file_name
    if not file_path.exists():
        return {
            "backend": "skeleton",
            "success": False,
            "error": f"Module file not found: {file_name}",
            "snapshot": FAST_NATIVE_SNAPSHOT,
            "module": module,
            "file_path": str(file_path),
            "elapsed_ms": _elapsed_ms(start),
        }
    return {
        "backend": "skeleton",
        "success": True,
        "snapshot": FAST_NATIVE_SNAPSHOT,
        "module": module,
        "file_path": str(file_path),
        "content": file_path.read_text(encoding="utf-8"),
        "elapsed_ms": _elapsed_ms(start),
    }



def load_native_index(workspace_root: str) -> dict:
    start = time.perf_counter()
    index_path = _fast_native_root(workspace_root) / "__index__.py"
    native_summary = summary_native(workspace_root)["summary"]
    if not index_path.exists():
        _write_fast_native_package(workspace_root, _native_drawers(workspace_root), _native_diary_entries(workspace_root), _native_kg_triples(workspace_root))
    return {
        "backend": "skeleton",
        "exists": True,
        "index_path": str(index_path),
        "snapshots": [FAST_NATIVE_SNAPSHOT],
        "snapshot_summaries": [{
            "name": FAST_NATIVE_SNAPSHOT,
            "memory_count": native_summary["memory_count"],
            "task_description": native_summary["task_description"],
            "task_topics": native_summary["task_topics"],
            "top_topics": native_summary["top_topics"],
            "top_files": native_summary["top_files"],
        }],
        "global_top_topics": list(native_summary["top_topics"]),
        "global_top_files": list(native_summary["top_files"]),
        "global_task_topics": list(native_summary["task_topics"]),
        "latest_snapshot": FAST_NATIVE_SNAPSHOT,
        "snapshot_count": 1,
        "total_memory_count": native_summary["memory_count"],
        "index_text": index_path.read_text(encoding="utf-8") if index_path.exists() else _native_index_text(native_summary),
        "elapsed_ms": _elapsed_ms(start),
    }



def summary_for_native_snapshot(workspace_root: str) -> dict:
    start = time.perf_counter()
    summary = summary_native(workspace_root)["summary"]
    return {
        "backend": "skeleton",
        "summary": {
            "name": FAST_NATIVE_SNAPSHOT,
            "task_description": summary["task_description"],
            "task_topics": list(summary["task_topics"]),
            "memory_count": summary["memory_count"],
            "top_topics": list(summary["top_topics"]),
            "top_files": list(summary["top_files"]),
            "drawer_count": summary["drawers"],
            "diary_entry_count": summary["diary_entries"],
            "kg_triple_count": summary["kg_triples"],
        },
        "elapsed_ms": _elapsed_ms(start),
    }


# ---------------------------------------------------------------------------
# Combined fast surface: snapshot skeleton + fast_native Python skeleton
# ---------------------------------------------------------------------------


def _all_records(workspace_root: str) -> List[dict]:
    return _all_snapshot_records(workspace_root) + _native_records(workspace_root)



def search_all_fast(workspace_root: str, query: str, wing: Optional[str] = None, room: Optional[str] = None, limit: int = 5) -> dict:
    start = time.perf_counter()
    hits = []
    for record in _all_records(workspace_root):
        if wing and record.get("wing") != wing:
            continue
        if room and record.get("room") != room:
            continue
        score = _record_score(record, query)
        if score["score"] <= 0:
            continue
        enriched = dict(record)
        enriched["text"] = record.get("full_content") or record.get("preview", "")
        enriched["source_file"] = Path(str(record.get("source_file", "?"))).name
        enriched["local_score"] = round(score["score"], 3)
        enriched["similarity"] = enriched["local_score"]
        enriched["score_kind"] = "local_rule_score"
        enriched["projection_kind"] = "native_record" if record.get("record_type") != "snapshot" else "snapshot_record"
        enriched["score_breakdown"] = {k: v for k, v in score.items() if k != "score"}
        hits.append(enriched)
    hits.sort(
        key=lambda item: (
            -item["local_score"],
            -int(bool(item["score_breakdown"].get("preview_hit"))),
            -int(bool(item["score_breakdown"].get("task_description_hit"))),
            -int(item["score_breakdown"].get("file_hits", 0)),
            str(item.get("wing", "")),
            str(item.get("room", "")),
            str(item.get("snapshot", "")),
            int(item.get("index", -1) if item.get("index") is not None else -1),
            str(item.get("drawer_id", "")),
        )
    )
    return {
        "backend": "skeleton",
        "query": query,
        "filters": {"wing": wing, "room": room, "palace_path": str(skeleton_output_path(workspace_root))},
        "results": hits[:limit],
        "elapsed_ms": _elapsed_ms(start),
    }



def duplicate_all_fast(workspace_root: str, content: str, threshold: float = 0.9) -> dict:
    start = time.perf_counter()
    matches = list(check_duplicate_skeleton(workspace_root, content, threshold).get("matches", []))
    matches.extend(duplicate_native(workspace_root, content, threshold).get("matches", []))
    normalized_matches = []
    seen_keys = set()
    for match in matches:
        match_content = str(match.get("content", ""))
        normalized = {
            **match,
            "content": match_content[:200] + "..." if len(match_content) > 200 else match_content,
        }
        key = (normalized.get("id"), normalized.get("wing"), normalized.get("room"), normalized.get("content"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        normalized_matches.append(normalized)
    normalized_matches.sort(key=lambda item: (-float(item.get("similarity", 0.0)), str(item.get("wing", "")), str(item.get("room", "")), str(item.get("id", ""))))
    filtered_matches = [match for match in normalized_matches if float(match.get("similarity", 0.0)) >= threshold]
    return {
        "backend": "skeleton",
        "is_duplicate": bool(filtered_matches),
        "matches": filtered_matches,
        "threshold": threshold,
        "elapsed_ms": _elapsed_ms(start),
    }



def status_all_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    taxonomy = taxonomy_all_fast(workspace_root)
    total = int(_load_index_summary(workspace_root).get("total_memory_count", 0)) + int(summary_native(workspace_root)["summary"]["memory_count"])
    return {
        "backend": "skeleton",
        "total_drawers": total,
        "wings": taxonomy["wings"],
        "rooms": taxonomy["rooms"],
        "palace_path": str(skeleton_output_path(workspace_root)),
        "protocol": "fast_native_python_skeleton",
        "aaak_dialect": None,
        "elapsed_ms": _elapsed_ms(start),
    }



def taxonomy_all_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    skeleton = get_taxonomy_fast(workspace_root)
    native = taxonomy_native(workspace_root)
    merged: dict[str, dict[str, int]] = defaultdict(dict)
    for source in (skeleton.get("taxonomy", {}), native.get("taxonomy", {})):
        for wing, rooms in source.items():
            merged.setdefault(wing, {})
            for room, count in rooms.items():
                merged[wing][room] = merged[wing].get(room, 0) + int(count)
    wings = {wing: sum(rooms.values()) for wing, rooms in sorted(merged.items())}
    rooms = Counter()
    for room_map in merged.values():
        rooms.update(room_map)
    return {
        "backend": "skeleton",
        "taxonomy": {wing: dict(sorted(room_map.items())) for wing, room_map in sorted(merged.items())},
        "wings": wings,
        "rooms": dict(sorted(rooms.items())),
        "elapsed_ms": _elapsed_ms(start),
    }



def list_wings_all_fast(workspace_root: str) -> dict:
    result = taxonomy_all_fast(workspace_root)
    return {"backend": "skeleton", "wings": result["wings"], "elapsed_ms": result["elapsed_ms"]}



def list_rooms_all_fast(workspace_root: str, wing: Optional[str] = None) -> dict:
    start = time.perf_counter()
    taxonomy = taxonomy_all_fast(workspace_root)["taxonomy"]
    if wing:
        rooms = dict(sorted(taxonomy.get(wing, {}).items()))
    else:
        counts = Counter()
        for room_map in taxonomy.values():
            counts.update(room_map)
        rooms = dict(sorted(counts.items()))
    return {
        "backend": "skeleton",
        "wing": wing or "all",
        "rooms": rooms,
        "elapsed_ms": _elapsed_ms(start),
    }



def graph_stats_all_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    room_data: dict[str, dict] = defaultdict(lambda: {"wings": set(), "count": 0, "recent": ""})
    for source in (_snapshot_room_graph_nodes(workspace_root), _native_room_graph_nodes(workspace_root)):
        for room_name, data in source.items():
            room_data[room_name]["wings"].update(data.get("wings", set()))
            room_data[room_name]["count"] += int(data.get("count", 0))
            recent = str(data.get("recent", ""))
            if recent and recent > str(room_data[room_name].get("recent", "")):
                room_data[room_name]["recent"] = recent
    stats = _room_graph_stats_payload(room_data)
    stats.update(
        {
            "backend": "skeleton",
            "memory_count": len(_all_records(workspace_root)),
            "wing_count": len({wing for data in room_data.values() for wing in data["wings"]}),
            "room_count": stats["total_rooms"],
            "edge_count": stats["total_edges"],
            "elapsed_ms": _elapsed_ms(start),
        }
    )
    return stats



def top_topics_all_fast(workspace_root: str, snapshot: Optional[str] = None) -> dict:
    if snapshot == FAST_NATIVE_SNAPSHOT:
        return top_topics_native(workspace_root)
    if snapshot:
        return top_topics_fast(workspace_root, snapshot)
    start = time.perf_counter()
    counts = Counter()
    for record in _all_records(workspace_root):
        counts.update(record.get("topics", []))
    return {
        "backend": "skeleton",
        "topics": [{"topic": topic, "count": count} for topic, count in counts.most_common(10)],
        "elapsed_ms": _elapsed_ms(start),
    }



def top_files_all_fast(workspace_root: str, snapshot: Optional[str] = None) -> dict:
    if snapshot == FAST_NATIVE_SNAPSHOT:
        return top_files_native(workspace_root)
    if snapshot:
        return top_files_fast(workspace_root, snapshot)
    start = time.perf_counter()
    counts = Counter()
    for record in _all_records(workspace_root):
        counts.update([path for path in record.get("files", []) if path])
    return {
        "backend": "skeleton",
        "files": [{"path": path, "count": count} for path, count in counts.most_common(10)],
        "elapsed_ms": _elapsed_ms(start),
    }



def neighbors_all_fast(workspace_root: str, snapshot: str, node_index: int = None, drawer_id: str = None) -> dict:
    if snapshot == FAST_NATIVE_SNAPSHOT:
        if not drawer_id:
            return {
                "backend": "skeleton",
                "drawer_id": drawer_id,
                "neighbors": [],
                "error": "drawer_id is required for fast_native neighbors",
                "elapsed_ms": 0.0,
            }
        return neighbors_native(workspace_root, drawer_id)
    return neighbors_fast(workspace_root, snapshot=snapshot, node_index=node_index if node_index is not None else -1)



def traverse_all_fast(workspace_root: str, start_room: str, max_hops: int = 2) -> dict:
    start = time.perf_counter()
    room_data: dict[str, dict] = defaultdict(lambda: {"wings": set(), "count": 0, "recent": ""})
    for source in (_snapshot_room_graph_nodes(workspace_root), _native_room_graph_nodes(workspace_root)):
        for room_name, data in source.items():
            room_data[room_name]["wings"].update(data.get("wings", set()))
            room_data[room_name]["count"] += int(data.get("count", 0))
            recent = str(data.get("recent", ""))
            if recent and recent > str(room_data[room_name].get("recent", "")):
                room_data[room_name]["recent"] = recent
    traversal = _traverse_room_graph(room_data, start_room, max_hops)
    traversal.update(
        {
            "backend": "skeleton",
            "start_room": start_room,
            "max_hops": max_hops,
            "graph_model": "shared-room projection",
            "paths": [
                {"from": item.get("connected_via", [start_room])[0] if item.get("connected_via") else start_room, "to": item["room"], "depth": item["hop"]}
                for item in traversal.get("results", [])
                if item.get("hop", 0) > 0
            ],
            "elapsed_ms": _elapsed_ms(start),
        }
    )
    return traversal



def find_tunnels_all_fast(workspace_root: str, wing_a: Optional[str] = None, wing_b: Optional[str] = None) -> dict:
    start = time.perf_counter()
    room_data: dict[str, dict] = defaultdict(lambda: {"wings": set(), "count": 0, "recent": ""})
    for source in (_snapshot_room_graph_nodes(workspace_root), _native_room_graph_nodes(workspace_root)):
        for room_name, data in source.items():
            room_data[room_name]["wings"].update(data.get("wings", set()))
            room_data[room_name]["count"] += int(data.get("count", 0))
            recent = str(data.get("recent", ""))
            if recent and recent > str(room_data[room_name].get("recent", "")):
                room_data[room_name]["recent"] = recent
    return {
        "backend": "skeleton",
        "wing_a": wing_a,
        "wing_b": wing_b,
        "tunnels": _find_tunnels_payload(room_data, wing_a=wing_a, wing_b=wing_b),
        "graph_model": "shared-room projection",
        "elapsed_ms": _elapsed_ms(start),
    }



def list_snapshots_all_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    snapshots = list(_load_index_summary(workspace_root).get("snapshots", []))
    if FAST_NATIVE_SNAPSHOT not in snapshots:
        snapshots.append(FAST_NATIVE_SNAPSHOT)
    latest_snapshot = FAST_NATIVE_SNAPSHOT if _native_records(workspace_root) else _load_index_summary(workspace_root).get("latest_snapshot")
    return {
        "backend": "skeleton",
        "snapshots": snapshots,
        "latest_snapshot": latest_snapshot,
        "elapsed_ms": _elapsed_ms(start),
    }



def load_index_all_fast(workspace_root: str) -> dict:
    start = time.perf_counter()
    skeleton = _load_index_summary(workspace_root)
    native = summary_native(workspace_root)["summary"]
    snapshot_summaries = list(skeleton.get("snapshot_summaries", []))
    snapshot_summaries.append(
        {
            "name": FAST_NATIVE_SNAPSHOT,
            "memory_count": native["memory_count"],
            "task_description": native["task_description"],
            "task_topics": list(native["task_topics"]),
            "top_topics": list(native["top_topics"]),
            "top_files": list(native["top_files"]),
        }
    )
    snapshots = list(skeleton.get("snapshots", []))
    if FAST_NATIVE_SNAPSHOT not in snapshots:
        snapshots.append(FAST_NATIVE_SNAPSHOT)
    native_index = load_native_index(workspace_root)
    return {
        "backend": "skeleton",
        "exists": True,
        "index_path": str(native_index["index_path"]),
        "snapshots": snapshots,
        "snapshot_summaries": snapshot_summaries,
        "global_top_topics": [item["topic"] for item in top_topics_all_fast(workspace_root)["topics"][:5]],
        "global_top_files": [item["path"] for item in top_files_all_fast(workspace_root)["files"][:5]],
        "global_task_topics": list(skeleton.get("global_task_topics", [])) + list(native.get("task_topics", [])),
        "latest_snapshot": FAST_NATIVE_SNAPSHOT if native["memory_count"] else skeleton.get("latest_snapshot"),
        "snapshot_count": len(snapshots),
        "total_memory_count": int(skeleton.get("total_memory_count", 0)) + int(native["memory_count"]),
        "index_text": native_index["index_text"],
        "elapsed_ms": _elapsed_ms(start),
    }



def summary_for_any_snapshot(workspace_root: str, snapshot: str) -> dict:
    if snapshot == FAST_NATIVE_SNAPSHOT:
        return summary_for_native_snapshot(workspace_root)
    return summary_for_snapshot(workspace_root, snapshot)



def read_any_snapshot_module(workspace_root: str, snapshot: str, module: str) -> dict:
    if snapshot == FAST_NATIVE_SNAPSHOT:
        return read_native_module(workspace_root, module)
    return read_snapshot_module(workspace_root, snapshot, module)



def _clear_caches() -> None:
    _MODULE_CACHE.clear()
    _LITERAL_CACHE.clear()
    _CONSTRUCTOR_LIST_CACHE.clear()
    _SNAPSHOT_RECORD_CACHE.clear()
    _ALL_RECORDS_CACHE.clear()
    _GRAPH_COUNTS_CACHE.clear()



def refresh_fast_state() -> None:
    _clear_caches()

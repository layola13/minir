#!/usr/bin/env python3
"""
Fast MCP skeleton benchmark
==========================

Measures generation, index, and query latency for the skeleton-backed
`mempalace_fast_*` MCP tools, with side-by-side comparisons to the legacy
MCP read/query path where that comparison is meaningful.

Usage:
    python benchmarks/fastmcp_bench.py
    python benchmarks/fastmcp_bench.py --query autosave
    python benchmarks/fastmcp_bench.py --snapshot snapshot_20260408_150119_stop --query autosave
    python benchmarks/fastmcp_bench.py --sample-transcript

Notes:
- By default, this benchmark reads the current repository state and uses the
  latest generated skeleton snapshot from `.mempalace/skeleton/__index__.py`.
- With `--sample-transcript`, it measures `persist_autosave(...)` generation
  time in isolation inside a temporary workspace.
- Legacy search uses the original Qdrant-backed MCP search path.
- Fast search uses the local skeleton projection and is not semantically
  identical to legacy search.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from mempalace.autosave import persist_autosave
from mempalace.conversation_skeleton import index_output_path, snapshot_skeleton_output_path
from mempalace.skeleton_search import load_index


def _timed(fn, *args, **kwargs) -> tuple[Any, float]:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    wall_ms = round((time.perf_counter() - start) * 1000, 3)
    return result, wall_ms


def _sample_transcript_lines() -> list[str]:
    return [
        json.dumps(
            {
                "message": {
                    "role": "user",
                    "content": "Use the new py skeleton to replace the old palace interface and benchmark search speed across mempalace/autosave.py and mempalace/mcp_server.py.",
                }
            }
        ),
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "Okay, I will generate the skeleton and compare fast MCP against the original MCP read path.",
                }
            }
        ),
        json.dumps(
            {
                "message": {
                    "role": "user",
                    "content": "Also inspect benchmarks/BENCHMARKS.md and tests/test_autosave.py while comparing generation, indexing, and query speed.",
                }
            }
        ),
        json.dumps({"message": {"role": "assistant", "content": "Understood."}}),
    ]


def _measure_generation() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot = root / "benchmark_session.jsonl"
        snapshot.write_text("\n".join(_sample_transcript_lines()) + "\n", encoding="utf-8")

        persist_result, generation_ms = _timed(
            persist_autosave,
            snapshot_file=str(snapshot),
            wing="wing_benchmark",
            agent="benchmarker",
            workspace_root=str(root),
            trigger="stop",
            session_id="benchmark-session",
        )

        skeleton_dir = snapshot_skeleton_output_path(str(root), str(snapshot))
        index_path = index_output_path(str(root))
        index_data = load_index(str(root))
        return {
            "workspace_root": str(root),
            "snapshot_file": str(snapshot),
            "generation_wall_ms": generation_ms,
            "persist_result": {
                "memory_count": persist_result[0],
                "code_saved": persist_result[1],
            },
            "skeleton_dir_exists": skeleton_dir.exists(),
            "index_exists": index_path.exists(),
            "latest_snapshot": index_data.get("latest_snapshot"),
            "snapshot_count": index_data.get("snapshot_count", 0),
            "total_memory_count": index_data.get("total_memory_count", 0),
            "note": "persist_autosave(...) currently measures autosave generation work only. If no skeleton index is written in the temporary workspace, latest_snapshot and snapshot_count remain empty by design.",
        }


def _default_snapshot_from_repo() -> str | None:
    index_data = load_index(str(Path.cwd()))
    return index_data.get("latest_snapshot")


def _benchmark_repo(snapshot: str, query: str) -> dict:
    from mempalace import mcp_server

    legacy_index, legacy_index_wall = _timed(mcp_server.tool_skeleton_index)
    fast_index, fast_index_wall = _timed(mcp_server.tool_fast_skeleton_index)

    legacy_read, legacy_read_wall = _timed(mcp_server.tool_skeleton_read, snapshot, "summary")
    fast_read, fast_read_wall = _timed(mcp_server.tool_fast_skeleton_read, snapshot, "summary")
    fast_summary, fast_summary_wall = _timed(mcp_server.tool_fast_summary_for, snapshot)

    legacy_search, legacy_search_wall = _timed(mcp_server.tool_search, query, 5)
    fast_search, fast_search_wall = _timed(mcp_server.tool_fast_search, query, 5)
    fast_neighbors, fast_neighbors_wall = _timed(mcp_server.tool_fast_neighbors, snapshot, 0)
    fast_graph, fast_graph_wall = _timed(mcp_server.tool_fast_graph_stats)
    fast_status, fast_status_wall = _timed(mcp_server.tool_fast_status)

    return {
        "snapshot": snapshot,
        "query": query,
        "index": {
            "legacy_skeleton_index": {
                "wall_ms": legacy_index_wall,
                "exists": legacy_index.get("exists"),
            },
            "fast_skeleton_index": {
                "wall_ms": fast_index_wall,
                "reported_elapsed_ms": fast_index.get("elapsed_ms"),
                "snapshot_count": fast_index.get("snapshot_count"),
                "total_memory_count": fast_index.get("total_memory_count"),
            },
        },
        "read": {
            "legacy_skeleton_read": {
                "wall_ms": legacy_read_wall,
                "success": legacy_read.get("success"),
                "content_len": len(legacy_read.get("content", "")),
            },
            "fast_skeleton_read": {
                "wall_ms": fast_read_wall,
                "reported_elapsed_ms": fast_read.get("elapsed_ms"),
                "success": fast_read.get("success"),
                "content_len": len(fast_read.get("content", "")),
            },
            "fast_summary_for": {
                "wall_ms": fast_summary_wall,
                "reported_elapsed_ms": fast_summary.get("elapsed_ms"),
                "has_summary": "summary" in fast_summary,
            },
        },
        "query_results": {
            "legacy_search": {
                "wall_ms": legacy_search_wall,
                "error": legacy_search.get("error"),
                "result_count": len(legacy_search.get("results", [])) if isinstance(legacy_search.get("results"), list) else None,
            },
            "fast_search": {
                "wall_ms": fast_search_wall,
                "reported_elapsed_ms": fast_search.get("elapsed_ms"),
                "result_count": len(fast_search.get("results", [])),
            },
            "fast_neighbors": {
                "wall_ms": fast_neighbors_wall,
                "reported_elapsed_ms": fast_neighbors.get("elapsed_ms"),
                "neighbor_count": len(fast_neighbors.get("neighbors", [])),
            },
            "fast_graph_stats": {
                "wall_ms": fast_graph_wall,
                "reported_elapsed_ms": fast_graph.get("elapsed_ms"),
                "memory_count": fast_graph.get("memory_count"),
                "snapshot_count": fast_graph.get("snapshot_count"),
            },
            "fast_status": {
                "wall_ms": fast_status_wall,
                "reported_elapsed_ms": fast_status.get("elapsed_ms"),
                "snapshot_count": fast_status.get("snapshot_count"),
            },
        },
        "equivalence": {
            "same_result_count": legacy_search.get("results") is not None
            and len(legacy_search.get("results", [])) == len(fast_search.get("results", [])),
            "same_semantics": False,
            "note": "Fast search is a local skeleton projection and is not semantically identical to the legacy vector search.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the fast skeleton MCP path.")
    parser.add_argument("--query", default="autosave", help="Query string to benchmark against both legacy and fast search")
    parser.add_argument("--snapshot", default=None, help="Snapshot name to read from; defaults to latest snapshot in the repository")
    parser.add_argument(
        "--sample-transcript",
        action="store_true",
        help="Measure temporary transcript generation with persist_autosave before repository benchmarks",
    )
    args = parser.parse_args()

    output: dict[str, Any] = {
        "cwd": str(Path.cwd()),
    }

    if args.sample_transcript:
        output["generation"] = _measure_generation()

    snapshot = args.snapshot or _default_snapshot_from_repo()
    if snapshot is None:
        output["repo_benchmark_error"] = "No repository skeleton snapshot available. Generate one first or pass --sample-transcript for generation-only measurement."
    else:
        output["repo"] = _benchmark_repo(snapshot=snapshot, query=args.query)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

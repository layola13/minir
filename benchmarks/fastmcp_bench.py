import time
import json
from pathlib import Path
import os
import sys

# Ensure mimir is importable
sys.path.append(os.getcwd())

from mimir import mcp_server
from mimir.autosave import persist_autosave


def _timed(func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    wall_ms = round((time.perf_counter() - start) * 1000, 3)
    return result, wall_ms


def benchmark_mimir():
    print("🧠 Starting Mimir Performance Deep Dive...")

    results = {}

    # 1. Generation Test (if snapshots exist)
    snapshots_dir = Path(os.path.expanduser("~/.mimir/hook_state/transcript_snapshots"))
    all_jsonls = list(snapshots_dir.glob("**/*_stop.jsonl"))

    if all_jsonls:
        sample = all_jsonls[-1]
        print(f"  - Measuring generation from {sample.name}...")
        _, gen_ms = _timed(
            persist_autosave, str(sample), "bench", "bench", os.getcwd(), "stop", "bench-session"
        )
        results["generation_ms"] = gen_ms
    else:
        results["generation_ms"] = "N/A (No snapshots)"

    # 2. MCP Tool Latency
    print("  - Measuring MCP tool latencies...")
    tools_to_test = [
        ("status", mcp_server.tool_status, {}),
        ("index", mcp_server.tool_fast_skeleton_index, {}),
        ("search", mcp_server.tool_search, {"query": "autosave"}),
        ("kg_stats", mcp_server.tool_kg_stats, {}),
    ]

    results["tools"] = {}
    for name, func, kwargs in tools_to_test:
        _, wall = _timed(func, **kwargs)
        results["tools"][name] = f"{wall}ms"
        print(f"    * {name:10}: {wall}ms")

    # 3. Memory Footprint (Approx)
    results["memory_info"] = "Pure Python AST (No persistent DB process)"

    print("\n--- Final Mimir Report ---")
    print(json.dumps(results, indent=2))

    with open("benchmarks/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    benchmark_mimir()

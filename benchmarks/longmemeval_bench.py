import time
import json
import os
import sys
from pathlib import Path
import shutil
import tempfile
import argparse

# Ensure mimir is importable
sys.path.append(os.getcwd())

from mimir.autosave import persist_autosave
from mimir.skeleton_search import search_all_fast, status_all_fast


def benchmark_lme(data_file, limit=0):
    print(f"🧠 Mimir × LongMemEval Stress Test: {Path(data_file).name}")

    with open(data_file) as f:
        data = json.load(f)
    if limit > 0:
        data = data[:limit]

    tmp_workspace = tempfile.mkdtemp(prefix="mimir_lme_bench_")
    results = {"total_questions": len(data), "iterations": []}

    start_total = time.perf_counter()

    try:
        for idx, entry in enumerate(data):
            q_id = entry.get("id", f"q-{idx}")
            question = entry["question"]

            # 1. Ingest haystack sessions into skeleton
            # LongMemEval entries have their own mini-haystack.
            # We treat each haystack as a workspace state.
            it_workspace = Path(tmp_workspace) / q_id
            it_workspace.mkdir(parents=True, exist_ok=True)

            gen_start = time.perf_counter()
            for s_idx, sess in enumerate(entry["haystack_sessions"]):
                transcript_path = it_workspace / f"sess_{s_idx}.jsonl"
                with open(transcript_path, "w") as f:
                    for turn in sess:
                        f.write(json.dumps({"message": turn}) + "\n")

                persist_autosave(
                    str(transcript_path),
                    "bench",
                    "bench",
                    str(it_workspace),
                    "stop",
                    f"sess_{s_idx}",
                )
            gen_ms = (time.perf_counter() - gen_start) * 1000

            # 2. Query Test
            q_start = time.perf_counter()
            search_all_fast(str(it_workspace), query=question, limit=5)
            q_ms = (time.perf_counter() - q_start) * 1000

            # 3. Status Test (Stress index parsing)
            s_start = time.perf_counter()
            status_all_fast(str(it_workspace))
            stat_ms = (time.perf_counter() - s_start) * 1000

            results["iterations"].append(
                {
                    "id": q_id,
                    "gen_ms": round(gen_ms, 2),
                    "query_ms": round(q_ms, 2),
                    "status_ms": round(stat_ms, 2),
                }
            )

            if (idx + 1) % 10 == 0:
                print(f"  Processed {idx + 1}/{len(data)} | Last Query: {q_ms:5.2f}ms")

    finally:
        shutil.rmtree(tmp_workspace, ignore_errors=True)

    total_elapsed = time.perf_counter() - start_total

    print("\n--- LongMemEval Performance Summary ---")
    avg_gen = sum(i["gen_ms"] for i in results["iterations"]) / len(results["iterations"])
    avg_query = sum(i["query_ms"] for i in results["iterations"]) / len(results["iterations"])
    avg_status = sum(i["status_ms"] for i in results["iterations"]) / len(results["iterations"])

    final_report = {
        "avg_haystack_ingest_ms": round(avg_gen, 2),
        "avg_query_latency_ms": round(avg_query, 2),
        "avg_status_latency_ms": round(avg_status, 2),
        "total_time_s": round(total_elapsed, 2),
        "throughput_qps": round(results["total_questions"] / total_elapsed, 2),
    }
    print(json.dumps(final_report, indent=2))

    with open("benchmarks/results_lme_perf.json", "w") as f:
        json.dump(final_report, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_file")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    benchmark_lme(args.data_file, args.limit)

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
from mimir.skeleton_search import search_all_fast

def benchmark_locomo(data_file, limit=0):
    print(f"🧠 Mimir × LoCoMo Stress Test: {Path(data_file).name}")
    
    with open(data_file) as f:
        data = json.load(f)
    if limit > 0:
        data = data[:limit]

    tmp_workspace = tempfile.mkdtemp(prefix="mimir_locomo_bench_")
    results = {"total_conversations": len(data), "total_questions": 0, "sessions": []}
    
    start_total = time.perf_counter()
    
    try:
        for conv_idx, sample in enumerate(data):
            sample_id = sample.get("sample_id", f"conv-{conv_idx}")
            qa_pairs = sample["qa"]
            
            # 1. Simulate Conversation & Persistence
            # We create a fake transcript for the conversation to generate a skeleton
            transcript_path = Path(tmp_workspace) / f"{sample_id}.jsonl"
            with open(transcript_path, "w") as f:
                for sess_num in range(1, 10): # dummy sessions
                    if f"session_{sess_num}" in sample["conversation"]:
                        for d in sample["conversation"][f"session_{sess_num}"]:
                            f.write(json.dumps({"message": d}) + "\n")
            
            # Measure skeleton generation
            gen_start = time.perf_counter()
            persist_autosave(str(transcript_path), "bench", "bench", tmp_workspace, "stop", sample_id)
            gen_ms = (time.perf_counter() - gen_start) * 1000
            
            # 2. Query Stress Test
            q_times = []
            for qa in qa_pairs:
                query = qa["question"]
                q_start = time.perf_counter()
                search_all_fast(tmp_workspace, query=query, limit=10)
                q_times.append((time.perf_counter() - q_start) * 1000)
            
            avg_q = sum(q_times) / len(q_times) if q_times else 0
            results["total_questions"] += len(qa_pairs)
            results["sessions"].append({
                "id": sample_id,
                "gen_ms": round(gen_ms, 2),
                "avg_query_ms": round(avg_q, 2),
                "p99_query_ms": round(sorted(q_times)[int(len(q_times)*0.99)], 2) if q_times else 0
            })
            
            print(f"  [{conv_idx+1}/{len(data)}] {sample_id:15} | Gen: {gen_ms:6.1f}ms | Avg Query: {avg_q:5.2f}ms")

    finally:
        shutil.rmtree(tmp_workspace, ignore_errors=True)

    total_elapsed = time.perf_counter() - start_total
    
    print("\n--- LoCoMo Performance Summary ---")
    avg_gen = sum(s["gen_ms"] for s in results["sessions"]) / len(results["sessions"])
    avg_query = sum(s["avg_query_ms"] for s in results["sessions"]) / len(results["sessions"])
    
    final_report = {
        "avg_skeleton_generation_ms": round(avg_gen, 2),
        "avg_query_latency_ms": round(avg_query, 2),
        "total_time_s": round(total_elapsed, 2),
        "throughput_qps": round(results["total_questions"] / total_elapsed, 2)
    }
    print(json.dumps(final_report, indent=2))
    
    with open("benchmarks/results_locomo_perf.json", "w") as f:
        json.dump(final_report, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_file")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    benchmark_locomo(args.data_file, args.limit)

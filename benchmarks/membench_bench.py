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

def benchmark_membench(data_dir, limit=0):
    print(f"🧠 Mimir × MemBench Stress Test: {data_dir}")
    
    # Just sample one typical file for performance testing
    data_path = Path(data_dir) / "simple.json"
    if not data_path.exists():
        # Try to find any json in the dir
        json_files = list(Path(data_dir).glob("*.json"))
        if not json_files:
            print(f"Error: No JSON data found in {data_dir}")
            return
        data_path = json_files[0]

    with open(data_path) as f:
        raw_data = json.load(f)
    
    # Flatten items from topic-keyed dict
    items = []
    for topic in raw_data:
        items.extend(raw_data[topic])
    
    if limit > 0:
        items = items[:limit]

    tmp_workspace = tempfile.mkdtemp(prefix="mimir_membench_bench_")
    results = {"total_items": len(items), "iterations": []}
    
    start_total = time.perf_counter()
    
    try:
        for idx, item in enumerate(items):
            item_id = f"item-{idx}"
            qa = item.get("QA", {})
            question = qa.get("question", "summary")
            messages = item.get("message_list", [])
            
            # 1. Generation Test
            it_workspace = Path(tmp_workspace) / item_id
            it_workspace.mkdir(parents=True, exist_ok=True)
            
            transcript_path = it_workspace / "transcript.jsonl"
            with open(transcript_path, "w") as f:
                # MemBench format varies, handle nested sessions or flat list
                sessions = messages if (messages and isinstance(messages[0], list)) else [messages]
                for s_idx, session in enumerate(sessions):
                    for turn in session:
                        # Normalize turn to Mimir format
                        user = turn.get("user") or turn.get("user_message", "")
                        asst = turn.get("assistant") or turn.get("assistant_message", "")
                        if user: f.write(json.dumps({"message": {"role": "user", "content": user}}) + "\n")
                        if asst: f.write(json.dumps({"message": {"role": "assistant", "content": asst}}) + "\n")

            gen_start = time.perf_counter()
            persist_autosave(str(transcript_path), "bench", "bench", str(it_workspace), "stop", item_id)
            gen_ms = (time.perf_counter() - gen_start) * 1000
            
            # 2. Query Test
            q_start = time.perf_counter()
            search_all_fast(str(it_workspace), query=question, limit=5)
            q_ms = (time.perf_counter() - q_start) * 1000
            
            results["iterations"].append({
                "id": item_id,
                "gen_ms": gen_ms,
                "query_ms": q_ms
            })
            
            if (idx + 1) % 20 == 0:
                print(f"  Processed {idx+1}/{len(items)} | Gen: {gen_ms:5.1f}ms | Query: {q_ms:5.2f}ms")

    finally:
        shutil.rmtree(tmp_workspace, ignore_errors=True)

    total_elapsed = time.perf_counter() - start_total
    
    print("\n--- MemBench Performance Summary ---")
    avg_gen = sum(i["gen_ms"] for i in results["iterations"]) / len(results["iterations"])
    avg_query = sum(i["query_ms"] for i in results["iterations"]) / len(results["iterations"])
    
    final_report = {
        "avg_item_ingest_ms": round(avg_gen, 2),
        "avg_query_latency_ms": round(avg_query, 2),
        "total_time_s": round(total_elapsed, 2),
        "throughput_qps": round(len(items) / total_elapsed, 2)
    }
    print(json.dumps(final_report, indent=2))
    
    with open("benchmarks/results_membench_perf.json", "w") as f:
        json.dump(final_report, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    benchmark_membench(args.data_dir, args.limit)

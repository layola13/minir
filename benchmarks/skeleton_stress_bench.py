import time
import json
import os
import sys
from pathlib import Path

# 确保 mimir 路径正确
sys.path.append(os.getcwd())

from mimir.skeleton_search import search_all_fast, load_index_all_fast

def skeleton_only_stress_test():
    workspace = os.getcwd()
    print(f"🧠 Mimir 骨架纯度压测开始 (工作区: {workspace})")
    
    # 1. 验证索引加载（这是所有检索的基础）
    start_idx = time.perf_counter()
    index = load_index_all_fast(workspace)
    idx_ms = (time.perf_counter() - start_idx) * 1000
    
    snapshot_count = len(index.get("snapshots", []))
    print(f"  - 发现骨架快照数量: {snapshot_count}")
    print(f"  - 骨架索引加载耗时: {idx_ms:.3f}ms")

    # 2. 模拟高频 AI 检索（连续 100 次不同关键词查询）
    test_keywords = ["autosave", "skeleton", "stress", "mempalace", "decision", "problem", "memory", "hook", "fast", "native"]
    
    latencies = []
    print(f"  - 正在执行 100 次纯骨架 AST 检索...")
    
    for i in range(100):
        query = test_keywords[i % len(test_keywords)]
        q_start = time.perf_counter()
        # 核心：search_all_fast 只会访问 .mimir/skeleton/ 下的 .py 文件
        res = search_all_fast(workspace, query=query, limit=5)
        latencies.append((time.perf_counter() - q_start) * 1000)

    # 3. 数据分析
    avg_latency = sum(latencies) / len(latencies)
    p99_latency = sorted(latencies)[99]
    qps = 1000 / avg_latency if avg_latency > 0 else 0

    print("\n--- Mimir 骨架检索性能报告 (SKELETON ONLY) ---")
    report = {
        "snapshots_scanned": snapshot_count,
        "avg_search_latency_ms": round(avg_latency, 3),
        "p99_search_latency_ms": round(p99_latency, 3),
        "index_load_ms": round(idx_ms, 3),
        "theoretical_qps": round(qps, 2)
    }
    print(json.dumps(report, indent=2))
    
    # 写入结果
    with open("benchmarks/skeleton_pure_perf.json", "w") as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    skeleton_only_stress_test()

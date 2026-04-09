# Fast MCP benchmark checkpoint

This document records the current verified state of the skeleton-backed `mimir_fast_*` benchmark work, with direct side-by-side comparison against the legacy MCP path.

## What is already working

The repository has a dedicated benchmark entrypoint for the fast skeleton MCP path:

- `benchmarks/fastmcp_bench.py`

It currently measures:

- temporary sample generation latency through `write_relationship_skeleton(...)` with `--sample-transcript`
- skeleton index latency
- skeleton module read latency
- legacy search latency
- fast search latency
- fast neighbors / graph stats / status latency

It also reports a simple equivalence summary:

- `same_result_count`
- `same_semantics`

## Benchmark commands that succeeded

```bash
python3 benchmarks/fastmcp_bench.py --query autosave
python3 benchmarks/fastmcp_bench.py --sample-transcript
```

## Latest successful measured output

Measured against:

- sample transcript generation in a temporary workspace
- repository snapshot: `snapshot_20260408_150119_stop`
- total snapshots from fast index: `7`
- total memory count from fast index: `303`

### Sample generation output

| Field | Value |
| --- | --- |
| generation mode | `write_relationship_skeleton` |
| generation wall time | `2.528 ms` |
| sample memory count | `2` |
| skeleton dir exists | `true` |
| index exists | `true` |
| latest snapshot | `snapshot_benchmark_session` |
| snapshot count | `1` |
| total memory count | `2` |

### Core performance comparison

| Operation | Legacy (`autosave`) | Fast (`autosave`) | Current comparison |
| --- | ---: | ---: | --- |
| skeleton index read | 0.120 ms | 48.207 ms | fast still pays aggregate index cost |
| skeleton summary read | 3.960 ms | 0.125 ms | fast is faster |
| search | 350.424 ms | 16.458 ms | fast is much faster |

### Additional fast-only timings

| Operation | Fast (`autosave`) | Notes |
| --- | ---: | --- |
| fast summary_for | 0.123 ms | direct snapshot summary lookup |
| fast neighbors | 0.258 ms | local graph lookup |
| fast graph_stats | 1.245 ms | now much cheaper than earlier iterations |
| fast status | 0.623 ms | cheap aggregate status read |

### Search comparison snapshot

| Query | same_result_count | same_semantics | Interpretation |
| --- | --- | --- | --- |
| `autosave` | true | false | fast returns the same number of results for this query while preserving its own local skeleton ordering model |

## MCP coverage status

The `fast_` MCP surface now has broad implementation coverage for the main legacy MCP methods.

Current fast methods exist for:

- status / taxonomy / rooms / wings
- skeleton index / skeleton read / snapshot listing / summary lookup
- search / duplicate check
- graph stats / traverse / find tunnels / neighbors
- top topics / top files
- AAAK spec
- knowledge graph query and mutation methods
- diary read and write methods
- drawer add and delete methods

These are not placeholder-only method names anymore. The current fast path includes local implementations for KG, diary, and drawer operations in the fast-native layer.

## Current conclusion

At the current stage:

- the fast path can answer the main MCP read/query surface locally
- the fast path also includes fast-native diary, drawer, and KG mutation/query operations
- the fast path is intentionally a local skeleton retrieval model rather than a vector-search clone
- the fast path is optimized around local skeleton structure, deterministic matching, and speed
- the fast path is clearly faster for local search
- the fast path is faster for snapshot summary reads
- the fast path still has a relatively heavy combined index read compared with the legacy plain-file index read
- the `fast_` MCP namespace is implemented, and the remaining work is about making the local skeleton behavior more correct, more consistent, and better tested on its own terms

## What improved in this checkpoint

Compared with the earlier checkpoint, the fast path has improved in four important ways:

1. repeated parsing overhead has been reduced through in-process caching
2. `fast_search` now also uses snapshot-level task metadata:
   - `task_description`
   - `task_topics`
   - stronger score breakdown and ranking signals
3. the `fast_` MCP namespace now has implemented KG, diary, and drawer operations in the fast-native layer
4. the sample benchmark generation path now produces a real temporary skeleton snapshot and index instead of reporting empty metadata by design

## Why the results differ

The legacy path uses Qdrant-backed semantic search.

The fast path uses local skeleton projection signals such as:

- preview text
- extracted topics
- file references
- memory type
- snapshot task description
- snapshot task topics

So the fast path is currently best understood as:

- a local matching and structure-aware retrieval layer
- a deterministic skeleton-native model whose usefulness should be judged by correctness, consistency, and speed

## Supporting implementation completed

The following work is already done:

- `mimir_fast_*` MCP tools added to `mimir/mcp_server.py`
- `mimir/skeleton_search.py` added as the fast skeleton query layer
- AST-based parsing improved for generated skeleton files
- transcript caveat noise filtered out of task description extraction
- in-process caching added for repeated skeleton reads and aggregate computations
- `fast_search` ranking expanded to include snapshot-level task metadata
- fast-native KG, diary, and drawer methods implemented locally
- benchmark instructions updated in `benchmarks/BENCHMARKS.md`
- sample benchmark generation updated to write a real temporary skeleton snapshot/index

## Verification status

Focused regression tests are currently passing:

```bash
python3 -m pytest tests/test_conversation_skeleton.py tests/test_autosave.py
```

Latest verified result:

- `12 passed`

## Next likely improvements

1. Add stricter tests for local skeleton search and duplicate behavior on richer mixed fixtures.
2. Continue improving fast search ordering when direct preview/topic/file/task signals should win.
3. Compare graph/tunnel counts against richer fixtures and tighten the local room-graph model where useful.
4. Keep benchmark docs aligned with current measured output.

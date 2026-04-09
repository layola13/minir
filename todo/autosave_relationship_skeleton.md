# Autosave relationship skeleton TODO

## Goal
- Keep existing autosave behavior for conversation memories and code diff / code summary.
- Add a minimal conversation relationship layer.
- Do not introduce Neo4j or any third-party database.
- Export the relationship result as a deterministic Python-like skeleton.

## Scope
1. Keep current hook flow in `hooks/mempal_save_hook.sh` and `hooks/mempal_precompact_hook.sh`.
2. Keep `mempalace/autosave.py` as the autosave entry point.
3. Reuse extracted conversation memories from `extract_memories(...)`.
4. Build lightweight relationships only:
   - `same_topic_as`
   - `follows_from`
   - `repeats_pattern`
   - `mentions_same_file`
   - `co_occurs_with`
5. Track simple metrics only:
   - frequency count
   - recency / latest source
   - support count
6. Export a compact Python-like skeleton artifact.

## Implementation steps
- Add a small helper/module to derive relationships from extracted memories.
- Add a formatter that renders a stable Python-like skeleton string.
- Call it from `persist_autosave(...)` after memory extraction.
- Store the skeleton as a dedicated autosave artifact.
- Avoid duplicate amplification by using stable relation signatures, not snapshot filename alone.
- Add tests for:
  - repeated topics
  - repeated file mentions
  - repeated patterns
  - deterministic skeleton output
  - autosave persistence of relationship artifact

## Verification
- Run focused pytest for autosave and relationship tests.
- Confirm git repos still store `code-diff`.
- Confirm non-git workspaces still store `code-summary`.
- Confirm a relationship skeleton artifact is generated from repeated conversational themes.

## Constraints
- Minimal intrusion.
- No commit yet.
- No third-party database.
- No broader transcript denoising beyond compact diff saving.

## Fast MCP 1:1 gap checklist

### Already implemented
- Fast native snapshot naming is now stable:
  - external snapshot id: `fast-native`
  - internal Python package directory: `fast_native`
- Fast native storage is using native Python skeleton modules rather than JSON or Python-wrapped JSON.
- Focused regression tests currently pass:
  - `python3 -m pytest tests/test_conversation_skeleton.py tests/test_autosave.py`
- Native implementations now exist for:
  - fast summary/index/module reads
  - fast search / duplicate / status / taxonomy / graph / snapshot reads
  - fast drawer add / delete
  - fast diary write / read
  - fast KG add / query / invalidate / timeline / stats
- First-round legacy parity tightening is now in place for:
  - fast status protocol and AAAK fields
  - fast diary empty-result message shape
  - fast drawer delete success/result shape
  - fast KG add / invalidate fact text shape
  - parity-oriented tests for status / taxonomy / duplicate / diary / KG / drawer / graph / tunnels / traverse

### Local skeleton fast MCP remaining work

#### 1. Search behavior should be correct for the local skeleton model
- `mempalace_fast_search` should optimize for deterministic local retrieval, not imitate vector search.
- Progress so far:
  - stable result shape is in place
  - ranking now prefers direct preview/task/file hits more consistently
  - filtering hooks exist for `wing` and `room`
- Remaining work:
  - verify richer edge-case queries return the intended local ordering
  - add stricter tests for preview/topic/file/task ranking on larger mixed fixtures
  - decide whether current `similarity` should stay as a generic local score or be renamed later for clarity

#### 2. Duplicate detection should be correct for the local skeleton model
- `mempalace_fast_check_duplicate` should use deterministic local duplicate logic, not vector similarity semantics.
- Progress so far:
  - threshold filtering is enforced in fast duplicate checks
  - match ordering and truncation are normalized more consistently
  - duplicate de-duplication is in place across snapshot/native records
- Remaining work:
  - test threshold behavior against richer local fixtures
  - tighten duplicate ranking for exact match / substring / token-overlap cases
  - decide whether current `similarity` naming should stay or become a clearer local score field later

#### 3. Taxonomy / graph / traverse / tunnel behavior should be internally consistent
- The current fast implementations are projection-based by design and should be judged by whether the local room-graph model is coherent and useful.
- Progress so far:
  - graph stats expose `total_rooms`, `tunnel_rooms`, `total_edges`, `rooms_per_wing`, and `top_tunnels`
  - tunnel payloads include `count` and `recent`
  - traverse exposes `results` plus missing-room error suggestions
- Remaining work:
  - validate counts and traversal behavior on richer local fixtures
  - tighten room connectivity semantics where the current projection is surprising
  - document intended projection semantics explicitly

#### 4. Drawer / diary / KG fast-native behavior still needs deeper local coverage
- These tools now have better core field parity and stricter edge-case regression coverage.
- Progress so far:
  - repeated drawer writes now have duplicate-path coverage
  - diary ordering under multiple writes now has regression coverage
  - KG repeated add / invalidate / expired-fact stats now have regression coverage
- Remaining work:
  - verify argument handling for more local edge cases
  - compare mixed multi-entity ordering/results against intended fast-native behavior
  - decide whether any remaining fast-native-only metadata should be removed for a cleaner surface

#### 5. Tests are still incomplete for the local model
- Current tests now check more shape parity and representative behavior.
- Remaining work:
  - add a per-tool local behavior matrix
  - add tests that compare outputs across richer local fixtures
  - decide which fields are stable API and which are implementation detail

#### 6. Benchmark follow-up
- Benchmark generation flow is now functional.
- Remaining work:
  - add cold vs warm measurements for index / graph operations
  - keep benchmark docs aligned with current measured output

### Current performance snapshot
- Fast search is already much faster than legacy search on current repo data.
- Fast read is already competitive with legacy read.
- Fast index and fast graph stats are much cheaper than earlier iterations.

### Priority order
1. Add richer tests for local search and duplicate behavior.
2. Tighten local ranking behavior on mixed fixtures.
3. Validate graph / taxonomy / tunnel semantics on richer local fixtures.
4. Deepen drawer / diary / KG edge-case coverage.
5. Add cold/warm benchmark measurements.

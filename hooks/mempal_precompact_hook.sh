#!/bin/bash
set -euo pipefail

STATE_DIR="$HOME/.mempalace/hook_state"
SNAPSHOT_ROOT="$STATE_DIR/transcript_snapshots"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPAL_WING="${MEMPAL_WING:-wing_claude_code}"
MEMPAL_AGENT="${MEMPAL_AGENT:-mempalace_hook}"
mkdir -p "$STATE_DIR" "$SNAPSHOT_ROOT"

INPUT=$(cat)

SESSION_ID=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null || printf 'unknown')
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || printf '')
TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

echo "[$(date '+%H:%M:%S')] PRE-COMPACT triggered for session $SESSION_ID" >> "$STATE_DIR/hook.log"

if [ ! -f "$TRANSCRIPT_PATH" ]; then
    cat <<'HOOKJSON'
{
  "decision": "block",
  "reason": "PreCompact auto-save could not run because the transcript file was unavailable. Save this session to MemPalace manually before compaction continues."
}
HOOKJSON
    exit 0
fi

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
SESSION_DIR="$SNAPSHOT_ROOT/$SESSION_ID"
SNAPSHOT_FILE="$SESSION_DIR/${TIMESTAMP}_precompact.jsonl"
mkdir -p "$SESSION_DIR"
cp "$TRANSCRIPT_PATH" "$SNAPSHOT_FILE"

if PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m mempalace mine "$SESSION_DIR" --mode convos --wing "$MEMPAL_WING" --agent "$MEMPAL_AGENT" >> "$STATE_DIR/hook.log" 2>&1; then
    echo "[$(date '+%H:%M:%S')] PRE-COMPACT auto-save persisted successfully -> $SNAPSHOT_FILE" >> "$STATE_DIR/hook.log"
    echo "{}"
else
    cat <<HOOKJSON
{
  "decision": "block",
  "reason": "PreCompact auto-save failed after snapshotting $SNAPSHOT_FILE. Check ~/.mempalace/hook_state/hook.log and save manually before compaction continues."
}
HOOKJSON
fi

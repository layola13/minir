#!/usr/bin/env python3
"""
Mimir MCP Server — Pure Fast Skeleton-backed memory access
==============================================================
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("mimir_mcp")

try:
    from mimir.skeleton_search import (
        diary_read_fast,
        diary_write_fast,
        kg_add_fast,
        kg_query_fast,
        kg_stats_fast,
        load_index_all_fast,
        search_all_fast,
        status_all_fast,
    )
    from mimir.autosave import persist_autosave
except Exception as e:
    logger.error(f"Critical Import Error: {e}")
    sys.exit(1)

PALACE_PROTOCOL = """IMPORTANT — Mimir Memory Protocol:
1. ON WAKE-UP: Call mimir_status to load palace overview.
2. BEFORE RESPONDING: call mimir_kg_query or mimir_search FIRST.
3. IF UNSURE: say \"let me check\" and query the palace.
4. AUTO-SAVE: Call mimir_autosave periodically (every ~15 messages) to persist the relationship skeleton."""

AAAK_SPEC = """AAAK Dialect: Compact human/LLM-readable memory."""

def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _write_response(payload: Dict[str, Any], io_mode: str) -> None:
    if io_mode == "line":
        sys.stdout.write(_json(payload) + "\n")
        sys.stdout.flush()
        return

    body = _json(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header)
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _read_request() -> Optional[Tuple[Dict[str, Any], str]]:
    """
    Read one JSON-RPC request from stdin.

    Supports:
    - MCP stdio framing (Content-Length headers)
    - newline-delimited JSON (legacy fallback)
    """
    while True:
        first = sys.stdin.buffer.readline()
        if not first:
            return None

        if first in (b"\r\n", b"\n"):
            continue

        if first.lower().startswith(b"content-length:"):
            try:
                length = int(first.split(b":", 1)[1].strip())
            except Exception:
                logger.error("RPC Parse Error: invalid Content-Length header")
                return None

            # Consume optional headers until blank line.
            while True:
                line = sys.stdin.buffer.readline()
                if not line:
                    return None
                if line in (b"\r\n", b"\n"):
                    break

            body = sys.stdin.buffer.read(length)
            if len(body) != length:
                logger.error("RPC Parse Error: truncated framed body")
                return None
            try:
                return json.loads(body.decode("utf-8")), "framed"
            except Exception as e:
                logger.error(f"RPC Parse Error: {e}")
                continue

        # Legacy json-line mode fallback.
        try:
            text = first.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            return json.loads(text), "line"
        except Exception as e:
            logger.error(f"RPC Parse Error: {e}")
            continue

# ── CORE WRAPPERS ─────────────────────────────────────────────────────────────

def tool_status(): return tool_fast_status()
def tool_search(**kwargs): return tool_fast_search(**kwargs)
def tool_kg_query(**kwargs): return tool_fast_kg_query(**kwargs)
def tool_kg_add(**kwargs): return tool_fast_kg_add(**kwargs)
def tool_diary_write(**kwargs): return tool_fast_diary_write(**kwargs)
def tool_diary_read(**kwargs): return tool_fast_diary_read(**kwargs)

def tool_autosave(snapshot_file: str, session_id: str = "unknown", trigger: str = "manual"):
    try:
        workspace_root = os.getcwd()
        memory_count, wrote_skeleton = persist_autosave(
            snapshot_file=snapshot_file,
            wing="wing_mimir_mcp",
            agent="mimir_mcp_server",
            workspace_root=workspace_root,
            trigger=trigger,
            session_id=session_id
        )
        return {
            "status": "success" if wrote_skeleton else "failed",
            "memories_extracted": memory_count,
            "skeleton_written": wrote_skeleton
        }
    except Exception as e:
        logger.error(f"Autosave Error: {e}")
        return {"status": "error", "message": str(e)}

# ── FAST IMPLEMENTATIONS ──────────────────────────────────────────────────────

def tool_fast_status():
    res = status_all_fast(str(Path.cwd()))
    res.update({"protocol": PALACE_PROTOCOL, "aaak_dialect": AAAK_SPEC})
    return res

def tool_fast_skeleton_index(): return load_index_all_fast(str(Path.cwd()))
def tool_fast_search(query: str, limit: int = 5, wing: str = None, room: str = None): return search_all_fast(str(Path.cwd()), query=query, wing=wing, room=room, limit=limit)
def tool_fast_kg_query(entity: str, as_of: str = None, direction: str = "both"): return kg_query_fast(str(Path.cwd()), entity=entity, as_of=as_of, direction=direction)
def tool_fast_kg_add(subject: str, predicate: str, object: str, valid_from: str = None, source_closet: str = None): return kg_add_fast(str(Path.cwd()), subject=subject, predicate=predicate, object=object, valid_from=valid_from, source_closet=source_closet)
def tool_fast_kg_stats(): return kg_stats_fast(str(Path.cwd()))
def tool_fast_diary_write(agent_name: str, entry: str, topic: str = "general"): return diary_write_fast(str(Path.cwd()), agent_name=agent_name, entry=entry, topic=topic)
def tool_fast_diary_read(agent_name: str, last_n: int = 10): return diary_read_fast(str(Path.cwd()), agent_name=agent_name, last_n=last_n)

# ── TOOLS MAPPING ─────────────────────────────────────────────────────────────

TOOLS = {
    "mimir_status": {"description": "Palace status (Skeleton)", "input_schema": {"type": "object", "properties": {}}, "handler": tool_status},
    "mimir_search": {"description": "Fast skeleton search", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}, "handler": tool_search},
    "mimir_kg_query": {"description": "Query skeleton KG", "input_schema": {"type": "object", "properties": {"entity": {"type": "string"}}, "required": ["entity"]}, "handler": tool_fast_kg_query},
    "mimir_kg_add": {"description": "Add to skeleton KG", "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"}}, "required": ["subject", "predicate", "object"]}, "handler": tool_fast_kg_add},
    "mimir_diary_write": {"description": "Write to skeleton diary", "input_schema": {"type": "object", "properties": {"agent_name": {"type": "string"}, "entry": {"type": "string"}}, "required": ["agent_name", "entry"]}, "handler": tool_diary_write},
    "mimir_diary_read": {"description": "Read skeleton diary", "input_schema": {"type": "object", "properties": {"agent_name": {"type": "string"}}, "required": ["agent_name"]}, "handler": tool_diary_read},
    "mimir_autosave": {
        "description": "Persist conversation skeleton. Call this periodically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "snapshot_file": {"type": "string", "description": "Path to the conversation transcript"},
                "session_id": {"type": "string"},
                "trigger": {"type": "string", "default": "manual"}
            },
            "required": ["snapshot_file"]
        },
        "handler": tool_autosave
    },
    "mimir_skeleton_index": {"description": "Skeleton index", "input_schema": {"type": "object", "properties": {}}, "handler": tool_fast_skeleton_index},
}

# ── JSON-RPC ──────────────────────────────────────────────────────────────────

def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method, params, req_id = request.get("method", ""), request.get("params", {}), request.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mimir-fast", "version": "3.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": name, "description": tool["description"], "inputSchema": tool["input_schema"]}
                    for name, tool in TOOLS.items()
                ]
            },
        }
    if method == "tools/call":
        tool_name, tool_args = params.get("name"), params.get("arguments", {})
        if tool_name not in TOOLS:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        try:
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": _json(result)}]},
            }
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    response_mode = "framed"
    while True:
        try:
            packet = _read_request()
            if packet is None:
                break
            request, request_mode = packet
            response_mode = request_mode
            response = handle_request(request)
            if response:
                _write_response(response, response_mode)
        except Exception as e:
            logger.error(f"RPC Loop Error: {e}")

if __name__ == "__main__":
    main()

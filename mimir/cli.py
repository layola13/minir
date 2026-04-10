#!/usr/bin/env python3
"""
Mimir — Pure Python Skeleton Memory System.

Commands:
    mimir status                      Show skeleton status
    mimir search "query"              Find anything in the skeleton
    mimir wake-up                     Show wake-up context from skeleton
"""

import argparse
from pathlib import Path

from mimir.skeleton_search import (
    status_all_fast,
    search_all_fast,
    load_index_all_fast,
)

def cmd_status(args):
    workspace = str(Path.cwd())
    res = status_all_fast(workspace)
    print("\nMimir Skeleton Status:")
    print(f"  Total Drawers: {res.get('total_drawers', 0)}")
    if res.get('wings'):
        print(f"  Wings: {len(res['wings'])}")

def cmd_search(args):
    workspace = str(Path.cwd())
    res = search_all_fast(workspace, query=args.query, limit=args.results)
    matches = res.get("matches", [])
    print(f"\nFound {len(matches)} matches:")
    for m in matches:
        print(f"\n--- [{m.get('snapshot', 'unknown')}] Score: {m.get('similarity', 0)} ---")
        print(m.get("preview", ""))

def cmd_wakeup(args):
    workspace = str(Path.cwd())
    index = load_index_all_fast(workspace)
    if not index.get("exists"):
        print("No skeleton index found. Run some autosaves first.")
        return

    print("\nMimir Wake-up Context:")
    print("=" * 50)
    print(f"Latest Snapshot: {index.get('latest_snapshot')}")
    print(f"Global Topics: {index.get('global_task_topics', [])}")
    # Minimal wake-up for now
    print("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="Mimir Fast CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show skeleton status")

    p_search = sub.add_parser("search", help="Search the skeleton")
    p_search.add_argument("query", help="What to search for")
    p_search.add_argument("--results", type=int, default=5, help="Number of results")

    sub.add_parser("wake-up", help="Show wake-up context")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "status": cmd_status,
        "search": cmd_search,
        "wake-up": cmd_wakeup,
    }
    dispatch[args.command](args)

if __name__ == "__main__":
    main()

from mimir.conversation_skeleton import build_relationship_skeleton


def test_build_relationship_skeleton_groups_topics_files_and_patterns():
    memories = [
        {
            "content": "We should add autosave relationship tracking for mimir/autosave.py and keep a skeleton.",
            "memory_type": "decision",
            "chunk_index": 0,
        },
        {
            "content": "The relationship skeleton should mention mimir/autosave.py and repeated topic links.",
            "memory_type": "decision",
            "chunk_index": 1,
        },
        {
            "content": "This problem keeps repeating in autosave and should be visible in the skeleton.",
            "memory_type": "problem",
            "chunk_index": 2,
        },
    ]

    text, stats = build_relationship_skeleton(memories)

    assert "# __init__.py" in text
    assert "# nodes.py" in text
    assert "# topics.py" in text
    assert "# files.py" in text
    assert "# patterns.py" in text
    assert "# edges.py" in text
    assert "class RelationGraph:" in text
    assert "hard_edges" in text
    assert "same_topic_neighbors" in text
    assert "same_file_neighbors" in text
    assert "same_pattern_neighbors" in text
    assert "mimir/autosave.py" in text
    assert "topics=" in text
    assert "files=" in text
    assert "NODE_TYPES" in text
    assert "NODE_TOPICS" in text
    assert "NODE_FILES" in text
    assert "from mimir.summary import SNAPSHOT_NAME, TASK_DESCRIPTION, TASK_TOPICS, snapshot_overview" in text
    assert stats["memory_count"] == 3
    assert stats["edge_count"] >= 0

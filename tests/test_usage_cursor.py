"""Tests for Section 6 — Cursor SQLite metrics."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import axt


def _make_db(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE scored_commits (
            commitHash TEXT, branchName TEXT, scoredAt INTEGER,
            linesAdded INTEGER, linesDeleted INTEGER,
            humanLinesAdded INTEGER, humanLinesDeleted INTEGER,
            composerLinesAdded INTEGER, composerLinesDeleted INTEGER,
            v1AiPercentage TEXT, v2AiPercentage TEXT,
            commitMessage TEXT, commitDate TEXT
        )
    """)
    for row in rows:
        conn.execute("""
            INSERT INTO scored_commits VALUES (
                :commitHash, :branchName, :scoredAt,
                :linesAdded, :linesDeleted,
                :humanLinesAdded, :humanLinesDeleted,
                :composerLinesAdded, :composerLinesDeleted,
                :v1AiPercentage, :v2AiPercentage,
                :commitMessage, :commitDate
            )
        """, {
            "commitHash": "", "branchName": "", "scoredAt": 0,
            "linesAdded": 0, "linesDeleted": 0,
            "humanLinesAdded": 0, "humanLinesDeleted": 0,
            "composerLinesAdded": 0, "composerLinesDeleted": 0,
            "v1AiPercentage": None, "v2AiPercentage": None,
            "commitMessage": "", "commitDate": "",
            **row,
        })
    conn.commit()
    conn.close()


def test_load_cursor_metrics_missing_file(tmp_path: Path):
    assert axt.load_cursor_metrics(tmp_path / "nope.db") == []


def test_load_cursor_metrics_reads_rows(tmp_path: Path):
    db = tmp_path / "cursor.db"
    _make_db(db, [
        {"commitHash": "abc123", "commitDate": "2026-04-29", "linesAdded": 100,
         "humanLinesAdded": 60, "v2AiPercentage": "40.0", "commitMessage": "init"},
        {"commitHash": "def456", "commitDate": "2026-04-30", "linesAdded": 200,
         "humanLinesAdded": 100, "v2AiPercentage": "50.0", "commitMessage": "feat"},
    ])
    metrics = axt.load_cursor_metrics(db)
    assert len(metrics) == 2
    m = {x.commit_hash: x for x in metrics}
    assert m["abc123"].ai_percentage == 40.0
    assert m["def456"].lines_added == 200


def test_load_cursor_metrics_v1_fallback(tmp_path: Path):
    """When v2AiPercentage is null, fall back to v1AiPercentage."""
    db = tmp_path / "cursor.db"
    _make_db(db, [{
        "commitHash": "h", "v1AiPercentage": "33.3", "v2AiPercentage": None,
        "commitDate": "2026-04-29",
    }])
    metrics = axt.load_cursor_metrics(db)
    assert metrics[0].ai_percentage == 33.3


def test_load_cursor_metrics_since_until(tmp_path: Path):
    db = tmp_path / "cursor.db"
    _make_db(db, [
        {"commitHash": "old", "commitDate": "2026-04-29"},
        {"commitHash": "mid", "commitDate": "2026-04-30"},
        {"commitHash": "new", "commitDate": "2026-05-01"},
    ])
    metrics = axt.load_cursor_metrics(db, since="2026-04-30", until="2026-04-30")
    assert [m.commit_hash for m in metrics] == ["mid"]


def test_summarize_cursor_metrics_empty():
    s = axt.summarize_cursor_metrics([])
    assert s.total_commits == 0
    assert s.avg_ai_percentage == 0


def test_summarize_cursor_metrics_basic():
    metrics = [
        axt.CursorCommitMetrics(
            commit_hash="a", branch_name="", scored_at=0,
            lines_added=100, lines_deleted=20,
            human_lines_added=60, human_lines_deleted=10,
            composer_lines_added=40, composer_lines_deleted=10,
            ai_percentage=40.0, commit_message="", commit_date="",
        ),
        axt.CursorCommitMetrics(
            commit_hash="b", branch_name="", scored_at=0,
            lines_added=200, lines_deleted=40,
            human_lines_added=100, human_lines_deleted=20,
            composer_lines_added=100, composer_lines_deleted=20,
            ai_percentage=60.0, commit_message="", commit_date="",
        ),
    ]
    s = axt.summarize_cursor_metrics(metrics)
    assert s.total_commits == 2
    assert s.total_lines_added == 300
    assert s.ai_lines_added == 300 - 160  # = 140
    assert s.avg_ai_percentage == 50.0

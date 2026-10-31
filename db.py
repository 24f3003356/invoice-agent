
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DATABASE_PATH", "invoice_agent.db")


def now():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    connection = get_connection()

    try:
        connection.execute("PRAGMA journal_mode = WAL")

        connection.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                context_id TEXT NOT NULL,
                principal TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                state TEXT NOT NULL,
                task_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_owner
            ON tasks(principal, created_at);

            CREATE TABLE IF NOT EXISTS idempotency (
                principal TEXT NOT NULL,
                message_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                task_id TEXT NOT NULL,
                PRIMARY KEY (principal, message_id)
            );

            CREATE TABLE IF NOT EXISTS decision_cache (
                package_hash TEXT PRIMARY KEY,
                proposal_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
    finally:
        connection.close()


def create_or_get_task(principal, message_id, content_hash, task, batch_id):
    """
    Atomically create a task or return the result of an earlier
    equivalent message. A changed message with the same ID conflicts.
    """

    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT content_hash, task_id
            FROM idempotency
            WHERE principal = ? AND message_id = ?
            """,
            (principal, message_id)
        ).fetchone()

        if existing:
            if existing["content_hash"] != content_hash:
                connection.rollback()
                return "conflict", None

            row = connection.execute(
                """
                SELECT task_json FROM tasks
                WHERE task_id = ? AND principal = ?
                """,
                (existing["task_id"], principal)
            ).fetchone()

            if not row:
                connection.rollback()
                raise RuntimeError("Idempotency record has no task")

            saved_task = json.loads(row["task_json"])
            connection.commit()
            return "replay", saved_task

        timestamp = now()

        connection.execute(
            """
            INSERT INTO tasks (
                task_id, context_id, principal, batch_id,
                state, task_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["contextId"],
                principal,
                batch_id,
                task["status"]["state"],
                json.dumps(task, separators=(",", ":")),
                timestamp,
                timestamp
            )
        )

        connection.execute(
            """
            INSERT INTO idempotency (
                principal, message_id, content_hash, task_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (principal, message_id, content_hash, task["id"])
        )

        connection.commit()
        return "created", task

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_task(task_id, principal):
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT task_json FROM tasks
            WHERE task_id = ? AND principal = ?
            """,
            (task_id, principal)
        ).fetchone()

        return json.loads(row["task_json"]) if row else None

    finally:
        connection.close()


def list_tasks(principal):
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT task_json FROM tasks
            WHERE principal = ?
            ORDER BY created_at DESC
            """,
            (principal,)
        ).fetchall()

        return [json.loads(row["task_json"]) for row in rows]

    finally:
        connection.close()


def update_task(task_id, principal, task):
    """
    Update only a nonterminal task.
    Terminal task states cannot be modified.
    """

    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")

        row = connection.execute(
            """
            SELECT state FROM tasks
            WHERE task_id = ? AND principal = ?
            """,
            (task_id, principal)
        ).fetchone()

        if not row:
            connection.rollback()
            return "not_found"

        if row["state"] in ("TASK_STATE_COMPLETED", "TASK_STATE_CANCELED", "TASK_STATE_FAILED"):
            connection.rollback()
            return "terminal"

        connection.execute(
            """
            UPDATE tasks
            SET state = ?, task_json = ?, updated_at = ?
            WHERE task_id = ? AND principal = ?
            """,
            (
                task["status"]["state"],
                json.dumps(task, separators=(",", ":")),
                now(),
                task_id,
                principal
            )
        )

        connection.commit()
        return "updated"

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# Initialize tables when this module is imported.
init_db()

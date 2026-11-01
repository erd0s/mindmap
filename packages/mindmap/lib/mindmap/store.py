from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .errors import MindmapError, RouteCollisionError
from .paths import canonical_path, database_path, is_within, route_for_root
from .transcripts import read_transcript_batch


VALID_STATES = {"planned", "open", "settled"}
VALID_KINDS = {"goal", "thread", "decision", "task", "question", "note"}
MAX_NEW_ITEMS_PER_RECORD = 20
MAX_ROOT_ITEMS = 4
MAX_TREE_DEPTH = 10
MAX_CHECKPOINT_SUMMARY_LENGTH = 500
MAX_TITLE_LENGTH = 160
MAX_ITEM_SUMMARY_LENGTH = 1200
MAX_RESUME_LENGTH = 600
MAX_RECORD_PAYLOAD_BYTES = 100_000
CHRONOLOGY_NODE_PATTERN = re.compile(
    r"^(?:message|msg|turn|prompt|response|chat|tool[-_ ]?call|event)[-_ ]*\d+\b",
    re.IGNORECASE,
)
ACTION_LIKE_RESUME_PATTERN = re.compile(
    r"^(?:next\s*:\s*)?(?:continue\s+by\s+)?"
    r"(?:add|build|choose|complete|configure|create|debug|decide|define|deploy|"
    r"document|finish|fix|implement|install|investigate|prepare|remove|replace|"
    r"review|run|send|test|update|upgrade|validate|verify|write)\b",
    re.IGNORECASE,
)
CLOSED_OR_MAINTENANCE_RESUME_PATTERN = re.compile(
    r"^(?:no\b|none\b|nothing\b|done\b|complete(?:d)?\b|resolved\b|settled\b|"
    r"closed\b|reopen\b|monitor\b|maintain\b|keep\b|use\b|if\b|when\b|unless\b|"
    r"only\b|as\s+needed\b)",
    re.IGNORECASE,
)
EXPLICIT_CLOSURE_PATTERN = re.compile(
    r"(?:^(?:the\s+|this\s+)?(?:local\s+)?"
    r"(?:work|task|goal|project|installation|install|implementation|migration|review|"
    r"analysis|assessment|investigation|setup|upgrade|fix|decision|capture|integration)"
    r"\b[^.]{0,120}\b(?:is|are|was|were|has\s+been|have\s+been)\s+(?:now\s+)?"
    r"(?:complete|completed|resolved|finished|closed|done)\b|"
    r"^(?:complete|completed|resolved|finished|closed|done)\b|"
    r"\bno\s+(?:further|remaining|more)\s+(?:work|action|changes?|follow[- ]?up)\b|"
    r"\bnothing\s+remains\b)",
    re.IGNORECASE,
)
SUPERSEDED_PATTERN = re.compile(
    r"^(?:this|the)\s+(?:work|task|goal|project|plan|direction|approach|workflow|"
    r"implementation|root|branch)\b[^.]{0,100}\b(?:is|was|has\s+been)\s+"
    r"(?:superseded|replaced\s+by|abandoned|cancelled|canceled|"
    r"no\s+longer\s+(?:needed|required|active|current))\b",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def semantic_warnings(
    items: list[dict[str, Any]],
    latest_item_updates: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    """Return high-confidence, warning-only map inconsistencies."""
    warnings: list[dict[str, str]] = []
    for item in items:
        item_id = str(item["id"])
        state = str(item["state"])
        summary = str(item.get("summary") or "").strip()
        resume = str(item.get("resume") or "").strip()
        if (
            state == "settled"
            and resume
            and ACTION_LIKE_RESUME_PATTERN.search(resume)
            and not CLOSED_OR_MAINTENANCE_RESUME_PATTERN.search(resume)
            and not re.search(r"\b(?:if|when|unless)\b", resume, re.IGNORECASE)
        ):
            warnings.append({
                "code": "settled_action_resume",
                "item_id": item_id,
                "message": (
                    "Settled concept has an ordinary action-like resume. Clear it, "
                    "replace it with completion/maintenance/conditional-reopen guidance, "
                    "or reopen the concept."
                ),
            })
        if state != "settled" and summary and EXPLICIT_CLOSURE_PATTERN.search(summary):
            warnings.append({
                "code": "state_summary_contradiction",
                "item_id": item_id,
                "message": (
                    f"{state.title()} concept's summary explicitly describes completion. "
                    "Verify the state or rewrite the contradictory summary."
                ),
            })
        if (
            state != "settled"
            and item.get("parent_id") is None
            and SUPERSEDED_PATTERN.search(" ".join((summary, resume)))
        ):
            warnings.append({
                "code": "superseded_root_frontier",
                "item_id": item_id,
                "message": (
                    "Unsettled root describes itself as superseded, replaced, abandoned, "
                    "or no longer needed. Verify whether its frontier is stale."
                ),
            })
        update = latest_item_updates.get(item_id)
        operation = update.get("operation") if isinstance(update, dict) else None
        if (
            state != "settled"
            and isinstance(update, dict)
            and update.get("previous_state") == "settled"
            and isinstance(operation, dict)
            and operation.get("state") in {"open", "planned"}
            and not str(operation.get("summary") or "").strip()
            and not str(operation.get("resume") or "").strip()
        ):
            warnings.append({
                "code": "reversion_without_context",
                "item_id": item_id,
                "message": (
                    "Concept was reopened from settled without updating its summary or "
                    "resume. Record the evidence and a usable frontier."
                ),
            })
    return warnings


class Store:
    def __init__(self, path: str | Path | None = None):
        managed_path = path is None
        self.path = Path(path or database_path())
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if managed_path:
            os.chmod(self.path.parent, 0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        deadline = time.monotonic() + 10
        while True:
            try:
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
                if str(mode).lower() != "wal":
                    connection.execute("PRAGMA journal_mode = WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                    connection.close()
                    raise
                time.sleep(0.025)
        return connection

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise MindmapError(f"Database constraint rejected the update: {exc}") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._schema_lock, self.read_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY,
                    root_path TEXT NOT NULL UNIQUE,
                    route_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    concept_model_version INTEGER NOT NULL DEFAULT 2,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    deactivated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    host TEXT NOT NULL CHECK (host IN ('codex', 'claude', 'unknown')),
                    session_id TEXT NOT NULL,
                    transcript_path TEXT,
                    transcript_cursor INTEGER NOT NULL DEFAULT 0,
                    transcript_device INTEGER,
                    transcript_inode INTEGER,
                    transcript_anchor_length INTEGER NOT NULL DEFAULT 0,
                    transcript_anchor_hash TEXT,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    ended_at TEXT,
                    UNIQUE(host, session_id)
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    session_pk INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    interaction_id TEXT NOT NULL,
                    prompt_excerpt TEXT,
                    started_at TEXT NOT NULL,
                    checkpointed_at TEXT,
                    checkpoint_summary TEXT,
                    checkpoint_payload_hash TEXT,
                    tool_activity_generation INTEGER NOT NULL DEFAULT 0,
                    checkpoint_tool_activity_generation INTEGER,
                    last_tool_name TEXT,
                    last_tool_at TEXT,
                    last_assistant_message TEXT,
                    UNIQUE(session_pk, interaction_id)
                );
                CREATE TABLE IF NOT EXISTS turn_prompts (
                    id INTEGER PRIMARY KEY,
                    turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    prompt TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(turn_id, prompt_hash)
                );
                CREATE TABLE IF NOT EXISTS items (
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    item_id TEXT NOT NULL,
                    parent_id TEXT,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    resume TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL CHECK (state IN ('planned', 'open', 'settled')),
                    kind TEXT NOT NULL CHECK (kind IN ('goal', 'thread', 'decision', 'task', 'question', 'note')),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    settled_at TEXT,
                    source_session_pk INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
                    source_interaction_id TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(project_id, item_id),
                    FOREIGN KEY(project_id, parent_id) REFERENCES items(project_id, item_id)
                        DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    session_pk INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
                    interaction_id TEXT,
                    event_type TEXT NOT NULL,
                    item_id TEXT,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    session_pk INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    message_key TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    message_at TEXT,
                    source_offset INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_pk, message_key)
                );
                CREATE INDEX IF NOT EXISTS idx_projects_active ON projects(active, root_path);
                CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_pk, id);
                CREATE INDEX IF NOT EXISTS idx_turn_prompts_turn ON turn_prompts(turn_id, id);
                """
            )
        # executescript commits by design. Acquire a separate immediate write lock
        # before inspecting/upgrading columns so concurrent plugin processes cannot
        # both decide to add the same migration.
        with self.transaction() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(sessions)")
            }
            if "transcript_device" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN transcript_device INTEGER")
            if "transcript_inode" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN transcript_inode INTEGER")
            if "transcript_anchor_length" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN transcript_anchor_length INTEGER NOT NULL DEFAULT 0"
                )
            if "transcript_anchor_hash" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN transcript_anchor_hash TEXT")
            turn_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(turns)")
            }
            if "checkpoint_payload_hash" not in turn_columns:
                connection.execute("ALTER TABLE turns ADD COLUMN checkpoint_payload_hash TEXT")
            if "tool_activity_generation" not in turn_columns:
                connection.execute(
                    "ALTER TABLE turns ADD COLUMN tool_activity_generation INTEGER NOT NULL DEFAULT 0"
                )
            if "checkpoint_tool_activity_generation" not in turn_columns:
                connection.execute(
                    "ALTER TABLE turns ADD COLUMN checkpoint_tool_activity_generation INTEGER"
                )
            if "last_tool_name" not in turn_columns:
                connection.execute("ALTER TABLE turns ADD COLUMN last_tool_name TEXT")
            if "last_tool_at" not in turn_columns:
                connection.execute("ALTER TABLE turns ADD COLUMN last_tool_at TEXT")
            project_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(projects)")
            }
            if "concept_model_version" not in project_columns:
                connection.execute(
                    "ALTER TABLE projects ADD COLUMN concept_model_version INTEGER NOT NULL DEFAULT 1"
                )
            item_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(items)")
            }
            if "resume" not in item_columns:
                connection.execute(
                    "ALTER TABLE items ADD COLUMN resume TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _event(
        self,
        connection: sqlite3.Connection,
        project_id: int,
        event_type: str,
        payload: dict[str, Any],
        *,
        session_pk: int | None = None,
        interaction_id: str | None = None,
        item_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO events
              (project_id, session_pk, interaction_id, event_type, item_id,
               payload_json, idempotency_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                session_pk,
                interaction_id,
                event_type,
                item_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                idempotency_key,
                utc_now(),
            ),
        )

    @staticmethod
    def _user_deleted_branches(
        connection: sqlite3.Connection, project_id: int
    ) -> list[dict[str, str]]:
        tombstones: dict[str, str] = {}
        for row in connection.execute(
            """
            SELECT id, event_type, item_id, payload_json FROM events
            WHERE project_id = ?
              AND event_type IN ('item.subtree_deleted', 'item.restored', 'item.created')
            ORDER BY id
            """,
            (project_id,),
        ):
            if row["event_type"] in {"item.restored", "item.created"}:
                if not isinstance(row["item_id"], str) or not row["item_id"].strip():
                    raise MindmapError(
                        f"Invalid {row['event_type']} event {row['id']}: concept id is missing."
                    )
                tombstones.pop(row["item_id"], None)
                continue
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError) as exc:
                raise MindmapError(
                    f"Invalid item.subtree_deleted event {row['id']}: malformed JSON payload."
                ) from exc
            if not isinstance(payload, dict):
                raise MindmapError(
                    f"Invalid item.subtree_deleted event {row['id']}: payload must be an object."
                )
            # Go's encoding/json matches struct fields without regard to case and
            # treats an explicit null pointer field as absent. Mirror that replay
            # contract because both runtimes consume the same event database.
            payload = {key.casefold(): value for key, value in payload.items()}
            has_deleted = payload.get("deleted") is not None
            has_details = payload.get("deleted_items") is not None
            if not has_deleted and not has_details:
                raise MindmapError(
                    f"Invalid item.subtree_deleted event {row['id']}: deleted ids are missing."
                )
            deleted_items = payload.get("deleted_items") if has_details else []
            if not isinstance(deleted_items, list):
                raise MindmapError(
                    f"Invalid item.subtree_deleted event {row['id']}: deleted_items must be a list."
                )
            detailed: dict[str, str] = {}
            for item in deleted_items:
                if isinstance(item, dict):
                    item = {key.casefold(): value for key, value in item.items()}
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("id"), str)
                    or not item["id"].strip()
                    or not (
                        item.get("title") is None
                        or isinstance(item.get("title"), str)
                    )
                    or item["id"] in detailed
                ):
                    raise MindmapError(
                        f"Invalid item.subtree_deleted event {row['id']}: deleted item details are invalid."
                    )
                detailed[item["id"]] = item.get("title") or item["id"]
            deleted = payload.get("deleted") if has_deleted else sorted(detailed)
            if (
                not isinstance(deleted, list)
                or not deleted
                or any(
                    not isinstance(item_id, str)
                    or not item_id.strip()
                    for item_id in deleted
                )
                or len(deleted) != len(set(deleted))
            ):
                raise MindmapError(
                    f"Invalid item.subtree_deleted event {row['id']}: deleted ids must be a non-empty unique string list."
                )
            if has_details and set(deleted) != set(detailed):
                raise MindmapError(
                    f"Invalid item.subtree_deleted event {row['id']}: id/title sets differ."
                )
            deleted_ids = deleted
            for item_id in deleted_ids:
                if isinstance(item_id, str) and item_id:
                    tombstones[item_id] = detailed.get(item_id, item_id)
        return [
            {"id": item_id, "title": tombstones[item_id]}
            for item_id in sorted(tombstones)
        ]

    def activate(self, root: str | Path) -> dict[str, Any]:
        root_path = str(canonical_path(root))
        route = route_for_root(root_path)
        name = Path(root_path).name
        now = utc_now()
        with self.transaction() as connection:
            collision = connection.execute(
                "SELECT * FROM projects WHERE route_path = ? COLLATE NOCASE AND root_path <> ?",
                (route, root_path),
            ).fetchone()
            if collision:
                raise RouteCollisionError(
                    f"{root_path} maps to {route}, which is already owned by "
                    f"{collision['root_path']}. Rename one path or choose a distinct project root."
                )
            connection.execute(
                """
                INSERT INTO projects
                  (root_path, route_path, name, active, concept_model_version,
                   created_at, updated_at, activated_at, deactivated_at)
                VALUES (?, ?, ?, 1, 2, ?, ?, ?, NULL)
                ON CONFLICT(root_path) DO UPDATE SET
                  active = 1, updated_at = excluded.updated_at,
                  activated_at = excluded.activated_at, deactivated_at = NULL
                """,
                (root_path, route, name, now, now, now),
            )
            project = connection.execute(
                "SELECT * FROM projects WHERE root_path = ?", (root_path,)
            ).fetchone()
            assert project is not None
            self._event(connection, project["id"], "project.activated", {"root_path": root_path})
        return self.get_project(project["id"]) or {}

    def deactivate(self, root: str | Path) -> dict[str, Any]:
        project = self.find_project(root, active_only=True)
        if not project:
            raise MindmapError(f"No active Mindmap project contains {canonical_path(root)}.")
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE projects SET active = 0, updated_at = ?, deactivated_at = ? WHERE id = ?",
                (now, now, project["id"]),
            )
            self._event(connection, project["id"], "project.deactivated", {})
        return self.get_project(project["id"]) or {}

    def find_project(self, path: str | Path, active_only: bool = False) -> dict[str, Any] | None:
        candidate = canonical_path(path)
        query = "SELECT * FROM projects"
        params: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY length(root_path) DESC"
        with self.read_connection() as connection:
            for row in connection.execute(query, params):
                if is_within(candidate, row["root_path"]):
                    return dict(row)
        return None

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            return self._row(connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())

    def project_by_route(self, route: str) -> dict[str, Any] | None:
        normalized = "/" + route.strip("/").lower()
        with self.read_connection() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM projects WHERE route_path = ? COLLATE NOCASE", (normalized,)
                ).fetchone()
            )

    def list_projects(self) -> list[dict[str, Any]]:
        with self.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT p.*,
                       (SELECT count(*) FROM items i WHERE i.project_id = p.id) AS item_count,
                       (SELECT count(*) FROM sessions s WHERE s.project_id = p.id) AS session_count,
                       (SELECT count(*) FROM items i WHERE i.project_id = p.id AND i.state = 'open') AS open_count,
                       (SELECT count(*) FROM items i WHERE i.project_id = p.id AND i.state = 'planned') AS planned_count
                FROM projects p ORDER BY p.updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def register_session(
        self,
        project_id: int,
        host: str,
        session_id: str,
        transcript_path: str | None = None,
        *,
        reopen: bool = False,
    ) -> dict[str, Any]:
        if host not in {"codex", "claude", "unknown"}:
            raise MindmapError(f"Unsupported host: {host}")
        if not session_id:
            raise MindmapError("A session id is required.")
        with self.transaction() as connection:
            return dict(
                self._register_session_tx(
                    connection, project_id, host, session_id, transcript_path, reopen=reopen
                )
            )

    def _register_session_tx(
        self,
        connection: sqlite3.Connection,
        project_id: int,
        host: str,
        session_id: str,
        transcript_path: str | None = None,
        *,
        reopen: bool = False,
    ) -> sqlite3.Row:
        if host not in {"codex", "claude", "unknown"}:
            raise MindmapError(f"Unsupported host: {host}")
        if not session_id:
            raise MindmapError("A session id is required.")
        now = utc_now()
        existing = connection.execute(
            "SELECT * FROM sessions WHERE host = ? AND session_id = ?", (host, session_id)
        ).fetchone()
        if existing and existing["project_id"] != project_id:
            raise MindmapError(
                f"Session {host}/{session_id} is already attached to a different project."
            )
        connection.execute(
            """
            INSERT INTO sessions
              (project_id, host, session_id, transcript_path, started_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(host, session_id) DO UPDATE SET
              transcript_cursor = CASE
                WHEN excluded.transcript_path IS NOT NULL
                 AND excluded.transcript_path <> sessions.transcript_path THEN 0
                ELSE sessions.transcript_cursor END,
              transcript_device = CASE
                WHEN excluded.transcript_path IS NOT NULL
                 AND excluded.transcript_path <> sessions.transcript_path THEN NULL
                ELSE sessions.transcript_device END,
              transcript_inode = CASE
                WHEN excluded.transcript_path IS NOT NULL
                 AND excluded.transcript_path <> sessions.transcript_path THEN NULL
                ELSE sessions.transcript_inode END,
              transcript_anchor_length = CASE
                WHEN excluded.transcript_path IS NOT NULL
                 AND excluded.transcript_path <> sessions.transcript_path THEN 0
                ELSE sessions.transcript_anchor_length END,
              transcript_anchor_hash = CASE
                WHEN excluded.transcript_path IS NOT NULL
                 AND excluded.transcript_path <> sessions.transcript_path THEN NULL
                ELSE sessions.transcript_anchor_hash END,
              transcript_path = COALESCE(excluded.transcript_path, sessions.transcript_path),
              last_seen_at = excluded.last_seen_at,
              ended_at = CASE WHEN ? THEN NULL ELSE sessions.ended_at END
            """,
            (project_id, host, session_id, transcript_path, now, now, int(reopen)),
        )
        session = connection.execute(
            "SELECT * FROM sessions WHERE host = ? AND session_id = ?", (host, session_id)
        ).fetchone()
        assert session is not None
        if not existing:
            self._event(
                connection,
                project_id,
                "session.started",
                {"host": host, "session_id": session_id},
                session_pk=session["id"],
            )
        return session

    def session(self, host: str, session_id: str) -> dict[str, Any] | None:
        with self.read_connection() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM sessions WHERE host = ? AND session_id = ?", (host, session_id)
                ).fetchone()
            )

    def begin_turn(
        self,
        project_id: int,
        session_pk: int,
        interaction_id: str,
        prompt: str = "",
    ) -> dict[str, bool]:
        now = utc_now()
        normalized_prompt = prompt.strip()
        excerpt = normalized_prompt[:500]
        prompt_hash = hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT id, checkpointed_at FROM turns
                WHERE session_pk = ? AND interaction_id = ?
                """,
                (session_pk, interaction_id),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO turns
                  (project_id, session_pk, interaction_id, prompt_excerpt, started_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_pk, interaction_id) DO UPDATE SET
                  prompt_excerpt = CASE
                    WHEN (turns.prompt_excerpt IS NULL OR turns.prompt_excerpt = '')
                      AND excluded.prompt_excerpt <> '' THEN excluded.prompt_excerpt
                    ELSE turns.prompt_excerpt END
                """,
                (project_id, session_pk, interaction_id, excerpt, now),
            )
            turn = connection.execute(
                """
                SELECT id, checkpointed_at FROM turns
                WHERE session_pk = ? AND interaction_id = ?
                """,
                (session_pk, interaction_id),
            ).fetchone()
            new_prompt = False
            if normalized_prompt:
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO turn_prompts
                      (turn_id, prompt, prompt_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (turn["id"], normalized_prompt, prompt_hash, now),
                )
                new_prompt = inserted.rowcount == 1
            checkpoint_invalidated = bool(
                existing and existing["checkpointed_at"] and new_prompt
            )
            if checkpoint_invalidated:
                connection.execute(
                    """
                    UPDATE turns SET checkpointed_at = NULL, checkpoint_summary = NULL,
                      checkpoint_payload_hash = NULL,
                      checkpoint_tool_activity_generation = NULL,
                      last_assistant_message = NULL
                    WHERE id = ?
                    """,
                    (turn["id"],),
                )
                self._event(
                    connection,
                    project_id,
                    "turn.checkpoint_invalidated",
                    {"reason": "additional_prompt", "prompt_hash": prompt_hash},
                    session_pk=session_pk,
                    interaction_id=interaction_id,
                    idempotency_key=(
                        f"checkpoint-invalidated:{session_pk}:{interaction_id}:{prompt_hash}"
                    ),
                )
            return {
                "new_prompt": new_prompt,
                "checkpoint_invalidated": checkpoint_invalidated,
            }

    def note_tool_activity(
        self,
        project_id: int,
        host: str,
        session_id: str,
        interaction_id: str | None,
        tool_name: str,
    ) -> dict[str, Any] | None:
        """Advance the active turn's tool generation before a tool executes.

        Claude does not currently attach a prompt id to PreToolUse, so its
        active turn is resolved as the latest turn in the session. Codex's
        turn_id is used directly when present.
        """
        now = utc_now()
        with self.transaction() as connection:
            session = connection.execute(
                """
                SELECT id FROM sessions
                WHERE project_id = ? AND host = ? AND session_id = ?
                """,
                (project_id, host, session_id),
            ).fetchone()
            if not session:
                return None
            if interaction_id:
                turn = connection.execute(
                    """
                    SELECT id, interaction_id, tool_activity_generation
                    FROM turns
                    WHERE session_pk = ? AND interaction_id = ?
                    """,
                    (session["id"], interaction_id),
                ).fetchone()
            else:
                turn = connection.execute(
                    """
                    SELECT id, interaction_id, tool_activity_generation
                    FROM turns
                    WHERE session_pk = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (session["id"],),
                ).fetchone()
            if not turn:
                return None
            generation = int(turn["tool_activity_generation"] or 0) + 1
            connection.execute(
                """
                UPDATE turns
                SET tool_activity_generation = ?, last_tool_name = ?, last_tool_at = ?
                WHERE id = ?
                """,
                (generation, tool_name[:200], now, turn["id"]),
            )
            return {
                "interaction_id": turn["interaction_id"],
                "tool_activity_generation": generation,
            }

    def turn_prompts(
        self, host: str, session_id: str, interaction_id: str
    ) -> list[dict[str, Any]]:
        session = self.session(host, session_id)
        if not session:
            raise MindmapError(f"Unknown session {host}/{session_id}.")
        with self.read_connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT tp.prompt, tp.prompt_hash, tp.created_at
                    FROM turn_prompts tp
                    JOIN turns t ON t.id = tp.turn_id
                    WHERE t.session_pk = ? AND t.interaction_id = ?
                    ORDER BY tp.id
                    """,
                    (session["id"], interaction_id),
                )
            ]

    def import_transcript(self, host: str, session_id: str) -> dict[str, Any]:
        total_imported = 0
        for _attempt in range(5):
            session = self.session(host, session_id)
            if not session:
                raise MindmapError(f"Unknown session {host}/{session_id}.")
            path = session.get("transcript_path")
            original_cursor = int(session["transcript_cursor"])
            if not path:
                return {"imported": total_imported, "cursor": original_cursor}
            expected_identity = (
                (int(session["transcript_device"]), int(session["transcript_inode"]))
                if session.get("transcript_device") is not None
                and session.get("transcript_inode") is not None
                else None
            )
            expected_anchor = (
                (int(session["transcript_anchor_length"]), str(session["transcript_anchor_hash"]))
                if int(session.get("transcript_anchor_length") or 0) > 0
                and session.get("transcript_anchor_hash")
                else None
            )
            batch = read_transcript_batch(
                path, host, original_cursor, expected_identity, expected_anchor
            )
            if not batch.source_available:
                # A host may rotate a transcript through a temporary rename. Keep
                # the last identity and cursor anchor so replacement detection is
                # still effective when the path returns.
                return {
                    "imported": total_imported,
                    "cursor": original_cursor,
                    "warnings": [f"Transcript source is temporarily unavailable: {path}"],
                }
            with self.transaction() as connection:
                current = connection.execute(
                    """
                    SELECT transcript_path, transcript_cursor, transcript_device, transcript_inode,
                           transcript_anchor_length, transcript_anchor_hash
                    FROM sessions WHERE id = ?
                    """,
                    (session["id"],),
                ).fetchone()
                if (
                    not current
                    or current["transcript_path"] != path
                    or int(current["transcript_cursor"]) != original_cursor
                    or current["transcript_device"] != session.get("transcript_device")
                    or current["transcript_inode"] != session.get("transcript_inode")
                    or int(current["transcript_anchor_length"] or 0)
                       != int(session.get("transcript_anchor_length") or 0)
                    or current["transcript_anchor_hash"] != session.get("transcript_anchor_hash")
                ):
                    continue
                imported = 0
                for message in batch.messages:
                    result = connection.execute(
                        """
                        INSERT OR IGNORE INTO messages
                          (project_id, session_pk, message_key, role, content, message_at, source_offset)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session["project_id"],
                            session["id"],
                            message.key,
                            message.role,
                            message.content,
                            message.timestamp,
                            message.source_offset,
                        ),
                    )
                    imported += result.rowcount
                for warning in batch.warnings:
                    warning_key = hashlib.sha256(
                        f"{batch.device}:{batch.inode}:{warning}".encode("utf-8")
                    ).hexdigest()
                    self._event(
                        connection,
                        session["project_id"],
                        "transcript.warning",
                        {"warning": warning, "path": path},
                        session_pk=session["id"],
                        idempotency_key=f"transcript-warning:{session['id']}:{warning_key}",
                    )
                connection.execute(
                    """
                    UPDATE sessions SET transcript_cursor = ?, transcript_device = ?,
                      transcript_inode = ?, transcript_anchor_length = ?,
                      transcript_anchor_hash = ?, last_seen_at = ? WHERE id = ?
                    """,
                    (
                        batch.cursor, batch.device, batch.inode, batch.anchor_length,
                        batch.anchor_hash, utc_now(), session["id"],
                    ),
                )
                return {
                    "imported": total_imported + imported,
                    "cursor": batch.cursor,
                    "warnings": list(batch.warnings),
                }
        raise MindmapError(
            f"Transcript source for {host}/{session_id} changed repeatedly during import; retry the sync."
        )

    def add_last_assistant_message(
        self, host: str, session_id: str, interaction_id: str, content: str
    ) -> None:
        session = self.session(host, session_id)
        if not session or not content.strip():
            return
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE turns SET last_assistant_message = ?
                WHERE session_pk = ? AND interaction_id = ?
                """,
                (content.strip(), session["id"], interaction_id),
            )

    def messages(self, host: str, session_id: str) -> list[dict[str, Any]]:
        session = self.session(host, session_id)
        if not session:
            raise MindmapError(f"Unknown session {host}/{session_id}.")
        with self.read_connection() as connection:
            return self._messages_for_session(connection, session["id"])

    def normalized_history(self, host: str, session_id: str) -> list[dict[str, Any]]:
        session = self.session(host, session_id)
        if not session:
            raise MindmapError(f"Unknown session {host}/{session_id}.")
        with self.read_transaction() as connection:
            messages = self._messages_for_session(connection, session["id"])
            known_assistant = {
                message["content"].strip()
                for message in messages
                if message["role"] == "assistant"
            }
            for turn in connection.execute(
                """
                SELECT interaction_id, last_assistant_message, started_at
                FROM turns WHERE session_pk = ? AND last_assistant_message IS NOT NULL
                ORDER BY id
                """,
                (session["id"],),
            ):
                content = turn["last_assistant_message"].strip()
                if content and content not in known_assistant:
                    messages.append(
                        {
                            "key": f"stop-fallback:{turn['interaction_id']}",
                            "role": "assistant",
                            "content": content,
                            "timestamp": turn["started_at"],
                            "source_offset": -1,
                            "fallback": True,
                        }
                    )
                    known_assistant.add(content)
            return messages

    @staticmethod
    def _messages_for_session(
        connection: sqlite3.Connection, session_pk: int
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT message_key AS key, role, content, message_at AS timestamp, source_offset
            FROM messages WHERE session_pk = ?
            ORDER BY CASE WHEN message_at IS NULL THEN 1 ELSE 0 END, message_at, source_offset, id
            """,
            (session_pk,),
        ).fetchall()
        return [dict(row) for row in rows]

    def prior_unresolved_checkpoint(
        self, host: str, session_id: str, interaction_id: str
    ) -> dict[str, Any] | None:
        """Return the latest completed-output turn not covered by a later checkpoint."""
        session = self.session(host, session_id)
        if not session:
            return None
        with self.read_connection() as connection:
            current = connection.execute(
                """
                SELECT id FROM turns
                WHERE session_pk = ? AND interaction_id = ?
                """,
                (session["id"], interaction_id),
            ).fetchone()
            if not current:
                return None
            return self._row(connection.execute(
                """
                SELECT missing.interaction_id, missing.last_tool_name,
                       missing.last_tool_at, missing.last_assistant_message
                FROM turns missing
                WHERE missing.session_pk = ? AND missing.id < ?
                  AND missing.checkpointed_at IS NULL
                  AND missing.last_assistant_message IS NOT NULL
                  AND trim(missing.last_assistant_message) <> ''
                  AND NOT EXISTS (
                    SELECT 1 FROM turns recovered
                    WHERE recovered.session_pk = missing.session_pk
                      AND recovered.id > missing.id AND recovered.id < ?
                      AND recovered.checkpointed_at IS NOT NULL
                  )
                ORDER BY missing.id DESC LIMIT 1
                """,
                (session["id"], current["id"], current["id"]),
            ).fetchone())

    def _validate_operation(self, operation: dict[str, Any]) -> None:
        action = operation.get("op")
        if not isinstance(action, str) or action not in {"upsert", "settle", "remove"}:
            raise MindmapError(
                f"Unsupported operation {action!r}; use 'upsert', 'settle', or 'remove'."
            )
        if "restore" in operation:
            if operation["restore"] is not True:
                raise MindmapError("restore must be true when supplied.")
            if action != "upsert":
                raise MindmapError("restore is valid only for an upsert operation.")
        allowed_fields = {
            "upsert": {
                "op", "id", "title", "summary", "resume", "state", "kind",
                "parent_id", "sort_order", "expected_revision", "restore",
            },
            "settle": {"op", "id", "title", "summary", "resume", "expected_revision"},
            "remove": {"op", "id", "expected_revision", "reparent_to"},
        }[action]
        unknown_fields = sorted(set(operation) - allowed_fields)
        if unknown_fields:
            raise MindmapError(
                f"Unsupported {action} field(s): {', '.join(unknown_fields)}."
            )
        item_id = operation.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise MindmapError("Every operation requires a non-empty string id.")
        if len(item_id) > 100:
            raise MindmapError("Item ids must be 100 characters or shorter.")
        for field in ("title", "summary", "resume"):
            if field in operation and not isinstance(operation[field], str):
                raise MindmapError(f"{field} must be a string when supplied.")
        field_limits = {
            "title": MAX_TITLE_LENGTH,
            "summary": MAX_ITEM_SUMMARY_LENGTH,
            "resume": MAX_RESUME_LENGTH,
        }
        for field, limit in field_limits.items():
            if isinstance(operation.get(field), str) and len(operation[field]) > limit:
                raise MindmapError(f"{field} must be {limit} characters or shorter.")
        if "parent_id" in operation:
            parent_id = operation["parent_id"]
            if parent_id is not None and (
                not isinstance(parent_id, str) or not parent_id.strip()
            ):
                raise MindmapError("parent_id must be a non-empty string or null.")
        if "reparent_to" in operation:
            reparent_to = operation["reparent_to"]
            if reparent_to is not None and (
                not isinstance(reparent_to, str) or not reparent_to.strip()
            ):
                raise MindmapError("reparent_to must be a non-empty string or null.")
        if "expected_revision" in operation:
            expected_revision = operation["expected_revision"]
            if (
                isinstance(expected_revision, bool)
                or not isinstance(expected_revision, int)
                or expected_revision < 1
            ):
                raise MindmapError("expected_revision must be a positive integer.")
        if isinstance(operation.get("title"), str) and not operation["title"].strip():
            raise MindmapError("title cannot be blank.")
        if "state" in operation:
            state = operation["state"]
            if not isinstance(state, str) or state not in VALID_STATES:
                raise MindmapError(f"Invalid state {state!r}.")
        if "kind" in operation:
            kind = operation["kind"]
            if not isinstance(kind, str) or kind not in VALID_KINDS:
                raise MindmapError(f"Invalid kind {kind!r}.")
        if "sort_order" in operation:
            sort_order = operation["sort_order"]
            if isinstance(sort_order, bool) or not isinstance(sort_order, int):
                raise MindmapError("sort_order must be an integer when supplied.")
            if not -(2**31) <= sort_order <= 2**31 - 1:
                raise MindmapError("sort_order must fit within a signed 32-bit integer.")

    @staticmethod
    def _assert_valid_graph(connection: sqlite3.Connection, project_id: int) -> None:
        parents = {
            row["item_id"]: row["parent_id"]
            for row in connection.execute(
                "SELECT item_id, parent_id FROM items WHERE project_id = ?", (project_id,)
            )
        }
        for item_id, parent_id in parents.items():
            if parent_id is not None and parent_id not in parents:
                raise MindmapError(
                    f"Item {item_id!r} refers to unknown parent {parent_id!r}."
                )
        root_count = sum(parent_id is None for parent_id in parents.values())
        if root_count > MAX_ROOT_ITEMS:
            raise MindmapError(
                f"A causal map may contain at most {MAX_ROOT_ITEMS} independent roots; merge related trains of thought."
            )
        for start in parents:
            seen: set[str] = set()
            current: str | None = start
            depth = 0
            while current is not None:
                if current in seen:
                    raise MindmapError(f"Parent relationships contain a cycle involving {current!r}.")
                seen.add(current)
                current = parents.get(current)
                depth += 1
                if depth > MAX_TREE_DEPTH:
                    raise MindmapError(
                        f"Causal branches may be at most {MAX_TREE_DEPTH} concepts deep; compress chronological or over-granular chains."
                    )

    def record(
        self,
        root: str | Path,
        host: str,
        session_id: str,
        interaction_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        project = self.find_project(root, active_only=True)
        if not project:
            raise MindmapError(f"No active Mindmap project contains {canonical_path(root)}.")
        allowed_payload_fields = {"summary", "operations", "concept_model"}
        unknown_payload_fields = sorted(set(payload) - allowed_payload_fields)
        if unknown_payload_fields:
            raise MindmapError(
                "Unsupported record field(s): " + ", ".join(unknown_payload_fields) + "."
            )
        if "operations" not in payload:
            raise MindmapError("A record payload must include an operations array.")
        operations = payload["operations"]
        if not isinstance(operations, list):
            raise MindmapError("operations must be a JSON array.")
        for operation in operations:
            if not isinstance(operation, dict):
                raise MindmapError("Each operation must be a JSON object.")
            self._validate_operation(operation)
        operation_ids = [operation["id"].strip() for operation in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise MindmapError("A record payload may operate on each concept id only once.")
        summary = payload.get("summary", "")
        if not isinstance(summary, str) or not summary.strip():
            raise MindmapError("A non-empty checkpoint summary is required.")
        if len(summary) > MAX_CHECKPOINT_SUMMARY_LENGTH:
            raise MindmapError(
                f"Checkpoint summary must be {MAX_CHECKPOINT_SUMMARY_LENGTH} characters or shorter."
            )
        concept_model = payload.get("concept_model")
        if concept_model is not None and concept_model != "causal-tree-v2":
            raise MindmapError("concept_model must be 'causal-tree-v2' when supplied.")
        canonical_payload = json.dumps(
            {
                "summary": summary.strip(),
                "operations": operations,
                **({"concept_model": concept_model} if concept_model else {}),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if len(canonical_payload.encode("utf-8")) > MAX_RECORD_PAYLOAD_BYTES:
            raise MindmapError(
                f"Record payload must be {MAX_RECORD_PAYLOAD_BYTES} bytes or smaller; compress transcript-scale detail."
            )
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        now = utc_now()
        changed: list[str] = []
        with self.transaction() as connection:
            locked_project = connection.execute(
                "SELECT * FROM projects WHERE id = ? AND active = 1", (project["id"],)
            ).fetchone()
            if not locked_project:
                raise MindmapError(
                    f"Mindmap tracking stopped for {project['root_path']} before this record could commit."
                )
            session = self._register_session_tx(
                connection, project["id"], host, session_id, reopen=False
            )
            if session["ended_at"] is not None:
                raise MindmapError(f"Session {host}/{session_id} has already ended.")
            already_done = connection.execute(
                """
                SELECT checkpointed_at, checkpoint_payload_hash FROM turns
                WHERE session_pk = ? AND interaction_id = ? AND checkpointed_at IS NOT NULL
                """,
                (session["id"], interaction_id),
            ).fetchone()
            if already_done:
                if already_done["checkpoint_payload_hash"] != payload_hash:
                    raise MindmapError(
                        f"Interaction {interaction_id!r} was already checkpointed with a different payload."
                    )
                return {
                    "project": project["route_path"],
                    "changed": [],
                    "checkpointed": True,
                    "idempotent_replay": True,
                }
            existing_ids = {
                row["item_id"]
                for row in connection.execute(
                    "SELECT item_id FROM items WHERE project_id = ?", (project["id"],)
                )
            }
            user_deleted = {
                item["id"]: item["title"]
                for item in self._user_deleted_branches(connection, project["id"])
            }
            new_ids = {
                operation["id"].strip()
                for operation in operations
                if operation["op"] == "upsert"
                and operation["id"].strip() not in existing_ids
            }
            if len(new_ids) > MAX_NEW_ITEMS_PER_RECORD:
                raise MindmapError(
                    f"One checkpoint may add at most {MAX_NEW_ITEMS_PER_RECORD} concepts; compress messages and implementation detail before recording."
                )
            for index, operation in enumerate(operations):
                item_id = operation["id"].strip()
                existing = connection.execute(
                    "SELECT * FROM items WHERE project_id = ? AND item_id = ?",
                    (project["id"], item_id),
                ).fetchone()
                action = operation["op"]
                restore = operation.get("restore", False)
                if restore and (existing or item_id not in user_deleted):
                    raise MindmapError(
                        f"Concept {item_id!r} is not a user-deleted concept and cannot be restored."
                    )
                if not existing and item_id in user_deleted and not restore:
                    raise MindmapError(
                        f"Concept {item_id!r} was explicitly deleted by the user; "
                        "set restore to true only when the user explicitly asks to restore it."
                    )
                if not existing and action == "upsert" and (
                    CHRONOLOGY_NODE_PATTERN.match(item_id)
                    or (
                        isinstance(operation.get("title"), str)
                        and CHRONOLOGY_NODE_PATTERN.match(operation["title"].strip())
                    )
                ):
                    raise MindmapError(
                        "New concept ids and titles must describe ideas, not numbered messages, turns, prompts, responses, tool calls, or events."
                    )
                expected_revision = operation.get("expected_revision")
                if existing:
                    if expected_revision is None:
                        raise MindmapError(
                            f"Existing concept {item_id!r} requires expected_revision {existing['revision']} to prevent a concurrent overwrite."
                        )
                    if expected_revision != existing["revision"]:
                        raise MindmapError(
                            f"Concept {item_id!r} changed concurrently: expected revision {expected_revision}, current revision {existing['revision']}. Sync and retry."
                        )
                elif expected_revision is not None:
                    raise MindmapError(
                        f"New concept {item_id!r} must not supply expected_revision."
                    )
                if action in {"settle", "remove"} and not existing:
                    raise MindmapError(f"Cannot {action} unknown item {item_id!r}.")
                if action == "remove":
                    has_children = connection.execute(
                        "SELECT 1 FROM items WHERE project_id = ? AND parent_id = ? LIMIT 1",
                        (project["id"], item_id),
                    ).fetchone()
                    if has_children and "reparent_to" not in operation:
                        raise MindmapError(
                            f"Concept {item_id!r} has children; supply reparent_to (including null for new roots)."
                        )
                    reparent_to = operation.get("reparent_to")
                    if isinstance(reparent_to, str):
                        reparent_to = reparent_to.strip()
                    if reparent_to == item_id:
                        raise MindmapError(f"Concept {item_id!r} cannot be reparented to itself.")
                    if reparent_to is not None and not connection.execute(
                        "SELECT 1 FROM items WHERE project_id = ? AND item_id = ?",
                        (project["id"], reparent_to),
                    ).fetchone():
                        raise MindmapError(
                            f"Cannot reparent children of {item_id!r} to unknown concept {reparent_to!r}."
                        )
                    if has_children:
                        operated_ids = set(operation_ids)
                        placeholders = ",".join("?" for _ in operated_ids)
                        revision_sql = (
                            f"CASE WHEN item_id IN ({placeholders}) THEN revision ELSE revision + 1 END"
                            if operated_ids
                            else "revision + 1"
                        )
                        connection.execute(
                            f"UPDATE items SET parent_id = ?, updated_at = ?, revision = {revision_sql} "
                            "WHERE project_id = ? AND parent_id = ?",
                            (reparent_to, now, *operated_ids, project["id"], item_id),
                        )
                    self._event(
                        connection,
                        project["id"],
                        "item.removed",
                        {"operation": operation},
                        session_pk=session["id"],
                        interaction_id=interaction_id,
                        item_id=item_id,
                        idempotency_key=(
                            f"record:{host}:{session_id}:{interaction_id}:{payload_hash}:{index}"
                        ),
                    )
                    connection.execute(
                        "DELETE FROM items WHERE project_id = ? AND item_id = ?",
                        (project["id"], item_id),
                    )
                    changed.append(item_id)
                    continue
                title = operation.get("title") or (existing["title"] if existing else None)
                if not title or not isinstance(title, str):
                    raise MindmapError(f"New item {item_id!r} requires a title.")
                state = "settled" if action == "settle" else operation.get(
                    "state", existing["state"] if existing else "open"
                )
                kind = operation.get("kind", existing["kind"] if existing else "thread")
                parent_id = operation.get("parent_id", existing["parent_id"] if existing else None)
                if isinstance(parent_id, str):
                    parent_id = parent_id.strip()
                item_summary = operation.get(
                    "summary", existing["summary"] if existing else ""
                )
                resume = operation.get(
                    "resume",
                    "" if action == "settle" else existing["resume"] if existing else "",
                )
                sort_order = operation.get(
                    "sort_order", existing["sort_order"] if existing else index
                )
                if parent_id == item_id:
                    raise MindmapError(f"Item {item_id!r} cannot be its own parent.")
                connection.execute(
                    """
                    INSERT INTO items
                      (project_id, item_id, parent_id, title, summary, resume, state, kind,
                       sort_order, created_at, updated_at, settled_at,
                       source_session_pk, source_interaction_id, revision)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(project_id, item_id) DO UPDATE SET
                      parent_id = excluded.parent_id,
                      title = excluded.title,
                      summary = excluded.summary,
                      resume = excluded.resume,
                      state = excluded.state,
                      kind = excluded.kind,
                      sort_order = excluded.sort_order,
                      updated_at = excluded.updated_at,
                      settled_at = excluded.settled_at,
                      source_session_pk = excluded.source_session_pk,
                      source_interaction_id = excluded.source_interaction_id,
                      revision = items.revision + 1
                    """,
                    (
                        project["id"],
                        item_id,
                        parent_id,
                        title.strip(),
                        item_summary.strip(),
                        resume.strip(),
                        state,
                        kind,
                        sort_order,
                        existing["created_at"] if existing else now,
                        now,
                        (
                            existing["settled_at"]
                            if existing and existing["state"] == "settled" and state == "settled"
                            else now if state == "settled" else None
                        ),
                        session["id"],
                        interaction_id,
                    ),
                )
                if restore:
                    event_type = "item.restored"
                elif existing:
                    event_type = "item.updated"
                else:
                    event_type = "item.created"
                self._event(
                    connection,
                    project["id"],
                    event_type,
                    {"operation": operation, "previous_state": existing["state"] if existing else None},
                    session_pk=session["id"],
                    interaction_id=interaction_id,
                    item_id=item_id,
                    idempotency_key=(
                        f"record:{host}:{session_id}:{interaction_id}:{payload_hash}:{index}"
                    ),
                )
                changed.append(item_id)
            if operations:
                self._assert_valid_graph(connection, project["id"])
            if concept_model:
                self._assert_valid_graph(connection, project["id"])
                connection.execute(
                    "UPDATE projects SET concept_model_version = 2 WHERE id = ?",
                    (project["id"],),
                )
            connection.execute(
                """
                INSERT INTO turns
                  (project_id, session_pk, interaction_id, prompt_excerpt, started_at,
                   checkpointed_at, checkpoint_summary, checkpoint_payload_hash,
                   tool_activity_generation, checkpoint_tool_activity_generation)
                VALUES (?, ?, ?, '', ?, ?, ?, ?, 0, 0)
                ON CONFLICT(session_pk, interaction_id) DO UPDATE SET
                  checkpointed_at = excluded.checkpointed_at,
                  checkpoint_summary = excluded.checkpoint_summary,
                  checkpoint_payload_hash = excluded.checkpoint_payload_hash,
                  checkpoint_tool_activity_generation = turns.tool_activity_generation
                """,
                (
                    project["id"], session["id"], interaction_id, now, now,
                    summary.strip(), payload_hash,
                ),
            )
            self._event(
                connection,
                project["id"],
                "turn.checkpointed",
                {"summary": summary.strip(), "changed": changed},
                session_pk=session["id"],
                interaction_id=interaction_id,
                idempotency_key=(
                    f"checkpoint:{host}:{session_id}:{interaction_id}:{payload_hash}"
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?", (now, project["id"])
            )
        return {"project": project["route_path"], "changed": changed, "checkpointed": True}

    def is_checkpointed(self, host: str, session_id: str, interaction_id: str) -> bool:
        session = self.session(host, session_id)
        if not session:
            return False
        with self.read_connection() as connection:
            row = connection.execute(
                """
                SELECT checkpointed_at FROM turns
                WHERE session_pk = ? AND interaction_id = ?
                """,
                (session["id"], interaction_id),
            ).fetchone()
            return bool(row and row["checkpointed_at"])

    def invalidate_checkpoint(
        self,
        host: str,
        session_id: str,
        interaction_id: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        session = self.session(host, session_id)
        if not session:
            return False
        with self.transaction() as connection:
            turn = connection.execute(
                """
                SELECT id, project_id, checkpointed_at, checkpoint_payload_hash
                FROM turns
                WHERE session_pk = ? AND interaction_id = ?
                """,
                (session["id"], interaction_id),
            ).fetchone()
            if not turn or not turn["checkpointed_at"]:
                return False
            connection.execute(
                """
                UPDATE turns SET checkpointed_at = NULL, checkpoint_summary = NULL,
                  checkpoint_payload_hash = NULL,
                  checkpoint_tool_activity_generation = NULL
                WHERE id = ?
                """,
                (turn["id"],),
            )
            payload = {"reason": reason, **(details or {})}
            self._event(
                connection,
                turn["project_id"],
                "turn.checkpoint_invalidated",
                payload,
                session_pk=session["id"],
                interaction_id=interaction_id,
                idempotency_key=(
                    f"checkpoint-invalidated:{session['id']}:{interaction_id}:"
                    f"{reason}:{turn['checkpoint_payload_hash']}"
                ),
            )
            return True

    def turn(self, host: str, session_id: str, interaction_id: str) -> dict[str, Any] | None:
        session = self.session(host, session_id)
        if not session:
            return None
        with self.read_connection() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM turns WHERE session_pk = ? AND interaction_id = ?",
                    (session["id"], interaction_id),
                ).fetchone()
            )

    def end_session(self, host: str, session_id: str) -> None:
        session = self.session(host, session_id)
        if not session:
            return
        with self.transaction() as connection:
            current = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session["id"],)
            ).fetchone()
            if not current or current["ended_at"] is not None:
                return
            now = utc_now()
            connection.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (now, session["id"]))
            self._event(
                connection,
                session["project_id"],
                "session.ended",
                {},
                session_pk=session["id"],
                idempotency_key=f"session-ended:{host}:{session_id}",
            )

    def project_snapshot(self, project_id: int) -> dict[str, Any]:
        with self.read_transaction() as connection:
            project, items = self._project_and_items(connection, project_id)
            latest_item_updates: dict[str, dict[str, Any]] = {}
            for row in connection.execute(
                """
                SELECT item_id, payload_json FROM events
                WHERE project_id = ? AND event_type = 'item.updated'
                ORDER BY id DESC
                """,
                (project_id,),
            ):
                item_id = row["item_id"]
                if item_id and item_id not in latest_item_updates:
                    try:
                        payload = json.loads(row["payload_json"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(payload, dict):
                        latest_item_updates[item_id] = payload
            sessions = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT host, session_id, started_at, last_seen_at, ended_at,
                           (SELECT count(*) FROM messages m WHERE m.session_pk = s.id) AS message_count,
                           (SELECT count(*) FROM turns t WHERE t.session_pk = s.id AND t.checkpointed_at IS NOT NULL) AS turn_count,
                           (SELECT count(*) FROM turns t
                            WHERE t.session_pk = s.id
                              AND t.checkpointed_at IS NULL
                              AND t.last_assistant_message IS NOT NULL
                              AND trim(t.last_assistant_message) <> ''
                              AND t.id > coalesce((
                                SELECT max(done.id) FROM turns done
                                WHERE done.session_pk = s.id
                                  AND done.checkpointed_at IS NOT NULL
                              ), 0)) AS unresolved_checkpoint_count
                    FROM sessions s WHERE project_id = ? ORDER BY last_seen_at DESC
                    """,
                    (project_id,),
                )
            ]
            events = []
            user_deleted_branches = self._user_deleted_branches(connection, project_id)
            for row in connection.execute(
                """
                SELECT e.id, e.event_type, e.item_id, e.interaction_id, e.payload_json,
                       e.created_at, s.host, s.session_id
                FROM events e LEFT JOIN sessions s ON s.id = e.session_pk
                WHERE e.project_id = ? ORDER BY e.id DESC LIMIT 200
                """,
                (project_id,),
            ):
                event = dict(row)
                event["payload"] = json.loads(event.pop("payload_json"))
                events.append(event)
        return {
            "project": project,
            "items": items,
            "semantic_warnings": semantic_warnings(items, latest_item_updates),
            "sessions": sessions,
            "events": events,
            "user_deleted_branches": user_deleted_branches,
        }

    @staticmethod
    def _project_and_items(
        connection: sqlite3.Connection, project_id: int
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        project_row = connection.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project_row:
            raise MindmapError(f"Unknown project id {project_id}.")
        items = [
            dict(row)
            for row in connection.execute(
                """
                SELECT item_id AS id, parent_id, title, summary, resume, state, kind,
                       sort_order, created_at, updated_at, settled_at, revision
                FROM items WHERE project_id = ?
                ORDER BY sort_order, created_at, item_id
                """,
                (project_id,),
            )
        ]
        return dict(project_row), items

    def project_view(self, project_id: int) -> dict[str, Any]:
        """Load only the materialized graph used by interactive frontends."""
        with self.read_transaction() as connection:
            project, items = self._project_and_items(connection, project_id)
        return {"project": project, "items": items}

    def context(self, root: str | Path, include_inactive: bool = False) -> str:
        project = self.find_project(root, active_only=not include_inactive)
        if not project:
            return "Mindmap is inactive for this directory."
        snapshot = self.project_snapshot(project["id"])
        project = snapshot["project"]
        items = snapshot["items"]
        user_deleted_branches = snapshot["user_deleted_branches"]
        warnings = snapshot["semantic_warnings"]
        children: dict[str | None, list[dict[str, Any]]] = {}
        for item in items:
            children.setdefault(item["parent_id"], []).append(item)
        lines = [
            (
                f"Mindmap is active for {project['root_path']} ({project['route_path']})."
                if project["active"]
                else f"Mindmap tracking is stopped for {project['root_path']} ({project['route_path']}); retained history follows."
            ),
            "Scope: this entire project directory; all agent sessions beneath it share this map until tracking is stopped.",
            (
                "Treat this as a compressed causal concept tree and update it only when the turn changes the thinking, decisions, explicit plans, or frontier."
                if project["active"]
                else "This is a read-only playback. Do not update or checkpoint it unless tracking is explicitly started again."
            ),
        ]
        if user_deleted_branches:
            lines.extend(
                [
                    "\nUSER-DELETED BRANCHES:",
                    "Do not recreate these concepts from retained or older transcript "
                    "evidence. Restore one only when the user explicitly asks, using "
                    "restore: true.",
                    *(
                        f"- [{item['id']}] {item['title']}"
                        for item in user_deleted_branches
                    ),
                ]
            )
        lines.append("\nCAUSAL TREE:")
        parents = {item["id"]: item["parent_id"] for item in items}
        overdeep = False
        for start in parents:
            depth = 0
            current: str | None = start
            while current is not None and depth <= MAX_TREE_DEPTH:
                current = parents.get(current)
                depth += 1
            if depth > MAX_TREE_DEPTH:
                overdeep = True
                break
        legacy_bounds = []
        root_count = len(children.get(None, []))
        if root_count > MAX_ROOT_ITEMS:
            legacy_bounds.append(f"{root_count} roots (limit {MAX_ROOT_ITEMS})")
        if overdeep:
            legacy_bounds.append(f"a branch deeper than {MAX_TREE_DEPTH}")
        if legacy_bounds:
            lines.extend(
                [
                    "LEGACY MAP OUTSIDE COMPRESSION BOUNDS: " + ", ".join(legacy_bounds) + ".",
                    "Do not expand this map. Run the injected snapshot command, then merge or remove transcript/task-board debris before adding concepts.",
                    "\nFRONTIER:",
                    "- Unavailable until the legacy map is compressed",
                ]
            )
            return "\n".join(lines)
        if not items:
            lines.append("- None")

        stack = [(item, 0) for item in reversed(children.get(None, []))]
        while stack:
            item, depth = stack.pop()
            indent = "  " * depth
            lines.append(
                f"{indent}- [{item['id']}] {item['title']} "
                f"({item['state']}, {item['kind']}, revision {item['revision']})"
            )
            if item["summary"]:
                lines.append(f"{indent}  Context: {item['summary']}")
            if item["resume"]:
                lines.append(f"{indent}  Resume: {item['resume']}")
            stack.extend(
                (child, depth + 1)
                for child in reversed(children.get(item["id"], []))
            )

        if project["active"] and warnings:
            lines.extend(
                [
                    "\nMINDMAP_SEMANTIC_WARNINGS_V1:",
                    "These are warning-only consistency checks. Reconcile the cited "
                    "concepts from conversation evidence; do not auto-settle causal parents.",
                    *(
                        f"- [{warning['code']}:{warning['item_id']}] {warning['message']}"
                        for warning in warnings
                    ),
                ]
            )

        frontier = [
            item for item in items
            if item["state"] != "settled" and not children.get(item["id"])
        ]
        lines.extend(
            [
                "\nFRONTIER:",
                "For resumed work, continue the matching frontier concept. Update it when the thought is unchanged; if the turn produces a genuinely new concept, parent it to the frontier it grew from—not to the root merely because this is a new session.",
            ]
        )
        if not frontier:
            lines.append("- None")
        for item in frontier:
            lines.append(f"- [{item['id']}] {item['title']} ({item['state']})")
            if item["resume"]:
                lines.append(f"  Resume: {item['resume']}")
        return "\n".join(lines)

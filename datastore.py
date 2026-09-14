# Datastore for Mei's persistent memories and user profiles.
# Uses SQLite for ACID safety, auto-syncing directly to users.md for human inspection.
import hashlib
import logging
import os
import re
import sqlite3
import tempfile
from pathlib import Path

logger = logging.getLogger("MeiDatastore")

DEFAULT_DB_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "mei_memory.db"
DEFAULT_MD_PATH = Path(__file__).resolve().parent / "users.md"


def generate_deterministic_id(name: str) -> int:
    # Python's built-in hash() changes across restarts (PYTHONHASHSEED).
    # Using sha256 gives a stable pseudo-ID for guests who lack a Discord user ID.
    digest = hashlib.sha256(name.lower().strip().encode("utf-8")).hexdigest()
    return int(digest[:14], 16)


class Datastore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, md_path: Path = DEFAULT_MD_PATH):
        self.db_path = db_path
        self.md_path = md_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

        # Import legacy or existing users.md if the DB is fresh
        if self.md_path.exists() and self._is_db_empty():
            logger.info("Fresh database detected. Bootstrapping memories from users.md...")
            self.import_from_markdown(self.md_path)

    def _get_connection(self) -> sqlite3.Connection:
        # SQLite handles WAL checkpoints automatically, keeping reads snappy while writes stay safe
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_tables(self):
        try:
            with self._get_connection() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'Server Member',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        fact TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'general',
                        confidence REAL NOT NULL DEFAULT 1.0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_user_fact ON memories(user_id, fact);
                """)
                # TODO: This works for now, but consider adding FTS5 table if memories ever hit 10k+ entries
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize SQLite tables: {e}")
            raise

    def _is_db_empty(self) -> bool:
        try:
            with self._get_connection() as conn:
                row = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()
                return (row["count"] == 0) if row else True
        except sqlite3.Error:
            return True

    def get_or_create_user(self, user_id: int, name: str, role: str | None = None) -> dict:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                # Update name if changed
                if name and row["name"] != name:
                    conn.execute(
                        "UPDATE users SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                        (name, user_id),
                    )
                if role and row["role"] != role:
                    conn.execute(
                        "UPDATE users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                        (role, user_id),
                    )
                return dict(row)

            # Auto-assign DT's role if detected
            default_role = (
                "Creator (DT)"
                if ("dt" in name.lower() or user_id == 897711166967664690)
                else "Server Member"
            )
            final_role = role or default_role
            conn.execute(
                "INSERT INTO users (user_id, name, role) VALUES (?, ?, ?)",
                (user_id, name, final_role),
            )
            return {"user_id": user_id, "name": name, "role": final_role}

    def add_facts(
        self,
        user_id: int,
        username: str,
        facts: list[str],
        role: str | None = None,
        category: str = "general",
    ) -> list[str]:
        # Clean and filter duplicates before hitting disk
        clean_facts = []
        for f in facts:
            txt = f.strip().lstrip("-*• ").strip()
            if len(txt) >= 3:
                clean_facts.append(txt)

        if not clean_facts:
            return []

        self.get_or_create_user(user_id, username, role)
        inserted = []

        with self._get_connection() as conn:
            for fact_text in clean_facts:
                try:
                    conn.execute(
                        """
                        INSERT INTO memories (user_id, fact, category)
                        VALUES (?, ?, ?)
                        ON CONFLICT(user_id, fact) DO NOTHING
                        """,
                        (user_id, fact_text, category),
                    )
                    # Check if row was actually inserted
                    if conn.total_changes > 0:
                        inserted.append(fact_text)
                        logger.info(f"[Mei Memory] Stored for {username} ({user_id}): {fact_text}")
                except sqlite3.Error as e:
                    logger.warning(f"Could not store fact '{fact_text}' for {user_id}: {e}")

        if inserted:
            self.export_to_markdown()
        return inserted

    def get_user_profile(self, user_id: int) -> dict | None:
        with self._get_connection() as conn:
            u_row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not u_row:
                return None
            m_rows = conn.execute(
                "SELECT fact, category, created_at FROM memories WHERE user_id = ? ORDER BY id ASC",
                (user_id,),
            ).fetchall()
            return {
                "user_id": u_row["user_id"],
                "name": u_row["name"],
                "role": u_row["role"],
                "facts": [m["fact"] for m in m_rows],
            }

    def clear_user_memories(self, user_id: int) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            cleared = conn.total_changes > 0
        if cleared:
            self.export_to_markdown()
        return cleared

    def find_user_id_by_name(self, name: str) -> int | None:
        clean = name.lower().strip()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM users WHERE LOWER(name) = ?", (clean,)
            ).fetchone()
            return row["user_id"] if row else None

    def get_all_users_summary(self) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT u.user_id, u.name, u.role, COUNT(m.id) as fact_count
                FROM users u
                LEFT JOIN memories m ON u.user_id = m.user_id
                GROUP BY u.user_id, u.name, u.role
                ORDER BY (CASE WHEN LOWER(u.role) LIKE '%creator%' THEN 0 ELSE 1 END), LOWER(u.name)
            """).fetchall()
            return [dict(r) for r in rows]

    def export_to_markdown(self, target_file: Path | None = None):
        out_path = target_file or self.md_path
        lines = [
            "# Mei's Dossier: Known Users",
            "",
            "This file is maintained by Mei. Whenever she decides to remember a fact about someone, she records it using her `<remember>` tool.",
            "",
        ]

        summaries = self.get_all_users_summary()
        with self._get_connection() as conn:
            for u in summaries:
                uid = u["user_id"]
                name = u["name"]
                role = u["role"]
                lines.append(f"## User: {name} (ID: {uid})")
                lines.append(f"- **Role/Relationship**: {role}")
                lines.append("- **Known Facts**:")

                facts = conn.execute(
                    "SELECT fact FROM memories WHERE user_id = ? ORDER BY id ASC", (uid,)
                ).fetchall()
                if facts:
                    for f in facts:
                        lines.append(f"  - {f['fact']}")
                else:
                    lines.append("  - (no specific facts noted yet)")
                lines.append("")

        content = "\n".join(lines)

        # Atomic write to prevent file corruption on Windows if interrupted
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(dir=out_path.parent, prefix="users_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_name, out_path)
            logger.debug(f"Exported dossier to {out_path.name}.")
        except OSError as e:
            logger.error(f"Failed atomic write for {out_path}: {e}")
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    def import_from_markdown(self, markdown_path: Path):
        if not markdown_path.exists():
            return

        try:
            content = markdown_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed reading {markdown_path}: {e}")
            return

        user_blocks = re.split(r"^## User:\s*", content, flags=re.MULTILINE)
        for block in user_blocks[1:]:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if not lines:
                continue

            header = lines[0]
            id_m = re.search(r"\((?:ID:\s*)?(\d+)\)", header)
            name_m = re.search(r"^(.*?)\s*\(", header)
            if not id_m:
                continue

            uid = int(id_m.group(1))
            name = name_m.group(1).strip() if name_m else f"User_{uid}"
            role = "Server Member"
            facts: list[str] = []
            in_facts = False

            for line in lines[1:]:
                if line.startswith(("- **Role/Relationship**:", "- **Relationship**:")):
                    role = line.split(":", 1)[1].strip()
                elif line.startswith("- **Known Facts**:"):
                    in_facts = True
                elif in_facts and line.startswith(("- ", "* ")):
                    fact_str = line[2:].strip()
                    if fact_str and not fact_str.startswith("("):
                        facts.append(fact_str)
                elif line.startswith("##"):
                    break

            self.get_or_create_user(uid, name, role)
            with self._get_connection() as conn:
                for f in facts:
                    conn.execute(
                        "INSERT INTO memories (user_id, fact) VALUES (?, ?) ON CONFLICT(user_id, fact) DO NOTHING",
                        (uid, f),
                    )
        logger.info(f"Imported dossier from {markdown_path.name} into SQLite datastore.")

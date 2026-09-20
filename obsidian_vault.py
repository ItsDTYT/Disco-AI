import datetime
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("DiscoVault")


def generate_deterministic_id(name: str) -> int:
    digest = hashlib.sha256(name.lower().strip().encode("utf-8")).hexdigest()
    return int(digest[:14], 16)


@dataclass(frozen=True)
class UserFact:
    content: str
    category: str = "general"
    recorded_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )


@dataclass
class UserNote:
    user_id: int
    username: str
    display_name: str
    role: str = "Server Member"
    tags: list[str] = field(default_factory=lambda: ["user", "disco-ai/memory"])
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )
    updated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )
    facts: list[UserFact] = field(default_factory=list)
    notes: str = ""

    def to_markdown(self) -> str:
        tag_list = "\n".join(f"  - {t}" for t in self.tags)
        lines = [
            "---",
            f"id: {self.user_id}",
            f"username: {self.username}",
            f"display_name: {self.display_name}",
            f"role: {self.role}",
            "tags:",
            tag_list,
            f"created_at: \"{self.created_at}\"",
            f"updated_at: \"{self.updated_at}\"",
            "---",
            "",
            f"# {self.display_name} ([[users/{self.user_id}|{self.username}]])",
            "",
            "## Profile",
            f"- **Discord ID**: `{self.user_id}`",
            f"- **Username**: `@{self.username}`",
            f"- **Role**: {self.role}",
            "",
            "## Observed Facts",
        ]
        if self.facts:
            for fact in self.facts:
                lines.append(f"- [x] {fact.content} <!-- category: {fact.category} | recorded: {fact.recorded_at} -->")
        else:
            lines.append("*(No observed facts recorded yet.)*")

        lines.append("")
        lines.append("## Notes")
        if self.notes:
            lines.append(self.notes.strip())
        else:
            lines.append("*(Autonomous interaction log active.)*")
        lines.append("")

        return "\n".join(lines)


class ObsidianVault:
    def __init__(self, vault_dir: Path | str):
        self.vault_dir = Path(vault_dir).resolve()
        self.users_dir = self.vault_dir / "users"
        self.index_file = self.vault_dir / "Index.md"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[int, UserNote] = {}
        self._name_index: dict[str, int] = {}
        self._load_all_notes()

    def _parse_frontmatter(self, text: str) -> tuple[dict[str, Any], str]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        if not match:
            return {}, text

        raw_yaml, body = match.group(1), match.group(2)
        metadata: dict[str, Any] = {}
        current_list_key: str | None = None

        for line in raw_yaml.splitlines():
            line_strip = line.strip()
            if not line_strip or line_strip.startswith("#"):
                continue

            if line.startswith("  - ") and current_list_key:
                metadata.setdefault(current_list_key, []).append(line_strip[4:].strip("\"'"))
                continue

            current_list_key = None
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip("\"'")
                if not val:
                    current_list_key = key
                    metadata[key] = []
                else:
                    metadata[key] = val

        return metadata, body

    def _parse_user_note(self, content: str, default_user_id: int = 0) -> UserNote:
        meta, body = self._parse_frontmatter(content)
        user_id = int(meta.get("id", default_user_id))
        username = meta.get("username", f"user_{user_id}")
        display_name = meta.get("display_name", username)
        role = meta.get("role", "Server Member")
        tags = meta.get("tags") or ["user", "disco-ai/memory"]
        created_at = meta.get("created_at", "")
        updated_at = meta.get("updated_at", "")

        facts: list[UserFact] = []
        notes_section = ""

        facts_match = re.search(r"## Observed Facts\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
        if facts_match:
            for line in facts_match.group(1).splitlines():
                line_str = line.strip()
                if line_str.startswith("- [x]") or line_str.startswith("- [ ]") or line_str.startswith("- "):
                    cleaned_fact = re.sub(r"^-\s*(\[[ xX]\]\s*)?", "", line_str)
                    cat_match = re.search(r"<!--\s*category:\s*([^|]+)\s*\|\s*recorded:\s*([^>]+)\s*-->", cleaned_fact)
                    category = "general"
                    recorded_at = ""
                    if cat_match:
                        category = cat_match.group(1).strip()
                        recorded_at = cat_match.group(2).strip()
                        cleaned_fact = re.sub(r"<!--.*?-->", "", cleaned_fact).strip()
                    if cleaned_fact and not cleaned_fact.startswith("*("):
                        facts.append(UserFact(content=cleaned_fact, category=category, recorded_at=recorded_at))

        notes_match = re.search(r"## Notes\s*\n(.*)$", body, re.DOTALL)
        if notes_match:
            raw_notes = notes_match.group(1).strip()
            if not raw_notes.startswith("*("):
                notes_section = raw_notes

        return UserNote(
            user_id=user_id,
            username=username,
            display_name=display_name,
            role=role,
            tags=tags if isinstance(tags, list) else [str(tags)],
            created_at=created_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            updated_at=updated_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            facts=facts,
            notes=notes_section,
        )

    def _load_all_notes(self) -> None:
        self._cache.clear()
        self._name_index.clear()
        for md_file in self.users_dir.glob("*.md"):
            try:
                user_id_str = md_file.stem
                if not user_id_str.isdigit():
                    continue
                user_id = int(user_id_str)
                text = md_file.read_text(encoding="utf-8")
                note = self._parse_user_note(text, default_user_id=user_id)
                self._cache[user_id] = note
                self._name_index[note.username.lower()] = user_id
                self._name_index[note.display_name.lower()] = user_id
            except (OSError, ValueError) as err:
                logger.warning("Failed loading Obsidian note %s: %s", md_file, err)

    def _write_user_note_atomic(self, note: UserNote) -> None:
        target_file = self.users_dir / f"{note.user_id}.md"
        tmp_file = self.users_dir / f"{note.user_id}.tmp"
        content = note.to_markdown()
        try:
            tmp_file.write_text(content, encoding="utf-8")
            os.replace(tmp_file, target_file)
            self._cache[note.user_id] = note
            self._name_index[note.username.lower()] = note.user_id
            self._name_index[note.display_name.lower()] = note.user_id
        except OSError as err:
            logger.error("Failed writing atomic note for user %d: %s", note.user_id, err)
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass
            raise

    def get_user_note(self, user_id: int) -> UserNote | None:
        return self._cache.get(user_id)

    def get_or_create_user(
        self, user_id: int, username: str, display_name: str, role: str | None = None
    ) -> UserNote:
        note = self.get_user_note(user_id)
        now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if note:
            dirty = False
            if username and note.username != username:
                note.username = username
                dirty = True
            if display_name and note.display_name != display_name:
                note.display_name = display_name
                dirty = True
            if role and note.role != role:
                note.role = role
                dirty = True
            if dirty:
                note.updated_at = now_ts
                self._write_user_note_atomic(note)
            return note

        new_note = UserNote(
            user_id=user_id,
            username=username,
            display_name=display_name,
            role=role or "Server Member",
            created_at=now_ts,
            updated_at=now_ts,
        )
        self._write_user_note_atomic(new_note)
        self.update_index_dashboard()
        return new_note

    def add_facts(
        self,
        user_id: int,
        username: str,
        display_name: str,
        facts: list[str],
        category: str = "general",
        role: str | None = None,
    ) -> list[str]:
        note = self.get_or_create_user(user_id, username, display_name, role)
        existing_facts_lower = {f.content.lower().strip() for f in note.facts}
        now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        added: list[str] = []

        for raw_f in facts:
            clean_f = re.sub(r"^[•\-*]\s*", "", raw_f).strip()
            clean_f = re.sub(r"\s+", " ", clean_f)
            if len(clean_f) < 3 or clean_f.lower() in existing_facts_lower:
                continue

            new_fact = UserFact(content=clean_f, category=category, recorded_at=now_ts)
            note.facts.append(new_fact)
            existing_facts_lower.add(clean_f.lower())
            added.append(clean_f)

        if added:
            note.updated_at = now_ts
            self._write_user_note_atomic(note)
            self.update_index_dashboard()

        return added

    def clear_user_facts(self, user_id: int) -> bool:
        note = self.get_user_note(user_id)
        if not note:
            return False
        note.facts.clear()
        note.updated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._write_user_note_atomic(note)
        self.update_index_dashboard()
        return True

    def get_all_users(self) -> list[UserNote]:
        return list(self._cache.values())

    def find_user_id_by_name(self, name: str) -> int | None:
        query = name.lower().strip().lstrip("@")
        return self._name_index.get(query)

    def update_index_dashboard(self) -> None:
        total_users = len(self._cache)
        total_facts = sum(len(n.facts) for n in self._cache.values())
        now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "---",
            "type: dashboard",
            "tags:",
            "  - disco-ai/dashboard",
            f"updated_at: \"{now_ts}\"",
            "---",
            "",
            "# Disco-AI Memory Vault",
            "",
            f"> Autonomous long-term memory store. Total Users: **{total_users}** | Total Recorded Facts: **{total_facts}**",
            "",
            "## User Dossier Index",
            "",
            "| Display Name | Username | Discord ID | Role | Facts | Last Updated |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for note in sorted(self._cache.values(), key=lambda n: n.display_name.lower()):
            link = f"[[users/{note.user_id}|{note.display_name}]]"
            lines.append(
                f"| {link} | `@{note.username}` | `{note.user_id}` | {note.role} | {len(note.facts)} | {note.updated_at} |"
            )

        lines.append("")
        lines.append("## Graph Tags")
        lines.append("- #user")
        lines.append("- #disco-ai/memory")
        lines.append("")

        tmp_file = self.vault_dir / "Index.tmp"
        try:
            tmp_file.write_text("\n".join(lines), encoding="utf-8")
            os.replace(tmp_file, self.index_file)
        except OSError as err:
            logger.error("Failed writing Obsidian vault Index.md: %s", err)
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

    def import_from_legacy_markdown(self, filepath: Path) -> int:
        if not filepath.exists():
            return 0

        content = filepath.read_text(encoding="utf-8")
        user_blocks = re.split(r"(?=^###\s+)", content, flags=re.MULTILINE)
        count = 0

        for block in user_blocks:
            lines = block.strip().splitlines()
            if not lines or not lines[0].startswith("### "):
                continue

            header = lines[0].replace("### ", "").strip()
            name_role_match = re.match(r"^(.+?)\s*\((.+?)\)$", header)
            if name_role_match:
                name = name_role_match.group(1).strip()
                role = name_role_match.group(2).strip()
            else:
                name = header
                role = "Server Member"

            user_id = generate_deterministic_id(name)
            facts: list[str] = []

            for line in lines[1:]:
                line_clean = line.strip()
                if line_clean.startswith("- ID:"):
                    id_str = line_clean.replace("- ID:", "").strip()
                    if id_str.isdigit():
                        user_id = int(id_str)
                elif line_clean.startswith("• ") or line_clean.startswith("- "):
                    f_text = re.sub(r"^[•\-]\s*", "", line_clean).strip()
                    if f_text and not f_text.startswith("ID:"):
                        facts.append(f_text)

            self.add_facts(
                user_id=user_id,
                username=name.lower().replace(" ", "_"),
                display_name=name,
                facts=facts,
                role=role,
            )
            count += 1

        self.update_index_dashboard()
        return count

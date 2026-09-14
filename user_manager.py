# User Manager for Mei Asahina.
# Thin wrapper around Datastore for Discord persona queries and <remember> tag extraction.
import logging
import re
from pathlib import Path

from datastore import Datastore, generate_deterministic_id

logger = logging.getLogger("MeiUserManager")

DEFAULT_USERS_MD = Path(__file__).resolve().parent / "users.md"


class UserManager:
    def __init__(self, filepath: Path = DEFAULT_USERS_MD, datastore: Datastore | None = None):
        self.filepath = filepath
        self.store = datastore or Datastore(md_path=filepath)

    @property
    def users(self) -> dict[int, dict]:
        # Backward-compatible property mapping: {uid: {name, role, facts}}
        profiles = {}
        for summary in self.store.get_all_users_summary():
            uid = summary["user_id"]
            p = self.store.get_user_profile(uid)
            if p:
                profiles[uid] = p
        return profiles

    def load(self):
        # Refresh from markdown file if someone edited users.md externally
        if self.filepath.exists():
            self.store.import_from_markdown(self.filepath)

    def save(self):
        self.store.export_to_markdown(self.filepath)

    def find_user_id_by_name(self, name: str) -> int | None:
        return self.store.find_user_id_by_name(name)

    def get_profile(self, user_id: int) -> dict | None:
        return self.store.get_user_profile(user_id)

    def get_summary_prompt(self, user_id: int, username: str) -> str:
        # Reminds Mei of her own past notes on this person (which she knows can change over time)
        profile = self.store.get_user_profile(user_id)
        if not profile or not profile.get("facts"):
            return ""

        role = profile.get("role", "Server Member")
        facts = profile.get("facts", [])
        # Cap to 10 most recent facts to avoid context bloat
        facts_preview = "; ".join(facts[:10])
        return f"[Mei's own observational dossier notes on {username} ({role}) - noted by Mei herself, subject to change: {facts_preview}]"

    def add_facts(
        self,
        user_id: int,
        username: str,
        new_facts: list[str],
        role: str | None = None,
        category: str = "general",
    ):
        self.store.add_facts(user_id, username, new_facts, role=role, category=category)

    def clear_user_facts(self, user_id: int):
        self.store.clear_user_memories(user_id)
        logger.info(f"Cleared dossier facts for user {user_id}.")

    def process_autonomous_remember_tags(
        self,
        raw_output: str,
        speaker_id: int | None = None,
        speaker_name: str | None = None,
        user_id: int | None = None,
        username: str | None = None,
    ) -> tuple[list[str], str]:
        # Parses <remember> and <note> tags from model output.
        # Supports target/user attributes and optional category attribute:
        # e.g. <remember user="Name" cat="gaming">fact</remember>
        actual_id = speaker_id if speaker_id is not None else (user_id or 0)
        actual_name = (
            speaker_name if speaker_name is not None else (username or f"User_{actual_id}")
        )

        # Regex matching tags like:
        # <remember>fact</remember>
        # <remember user="DT" category="gaming">fact</remember>
        tag_pat = re.compile(
            r"<(?:remember|note)(?:\s+([^>]+))?>([\s\S]*?)</(?:remember|note)>",
            re.IGNORECASE,
        )
        attr_pat = re.compile(
            r"(?:user|speaker|for|target|about|person)=['\"]?([^'\"\s>]+)['\"]?", re.IGNORECASE
        )
        cat_pat = re.compile(r"(?:cat|category|type)=['\"]?([^'\"\s>]+)['\"]?", re.IGNORECASE)

        recorded = []

        for attrs_str, content in tag_pat.findall(raw_output):
            attrs = attrs_str or ""
            u_match = attr_pat.search(attrs)
            c_match = cat_pat.search(attrs)

            target_name = u_match.group(1).strip() if u_match else ""
            category = c_match.group(1).strip() if c_match else "general"

            fact_lines = [l.strip().lstrip("-*• ") for l in content.splitlines() if l.strip()]
            if not fact_lines:
                continue

            if target_name:
                matched_id = self.store.find_user_id_by_name(target_name)
                if matched_id:
                    assigned_id = matched_id
                    assigned_name = target_name
                else:
                    # Deterministic hash so this guest retains their facts on next run
                    assigned_id = generate_deterministic_id(target_name)
                    assigned_name = target_name
            else:
                assigned_id = actual_id
                assigned_name = actual_name

            stored = self.store.add_facts(
                user_id=assigned_id,
                username=assigned_name,
                facts=fact_lines,
                category=category,
            )
            for f in stored:
                recorded.append(f"{assigned_name}: {f}")

        # Strip memory tags from user-facing text
        clean_text = tag_pat.sub("", raw_output).strip()
        return recorded, clean_text

    def get_user_display_card(self, user_id: int, username: str) -> str:
        # Formats markdown block for Discord slash command /facts
        profile = self.store.get_user_profile(user_id)
        if not profile or not profile.get("facts"):
            return f"i don't have any notes on you in my dossier yet, {username}."

        facts = profile.get("facts", [])
        role = profile.get("role", "server member")
        fact_lines = "\n".join([f"• {f}" for f in facts])
        return f"**dossier: {username}** ({role.lower()}):\n" f"{fact_lines}"

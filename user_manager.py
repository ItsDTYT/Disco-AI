# User Manager for Disco-AI.
# Queries persistent memory profiles and extracts autonomous <remember> tags from bot outputs.
import logging
import re
from pathlib import Path

from datastore import Datastore, generate_deterministic_id

logger = logging.getLogger("DiscoUserManager")

DEFAULT_USERS_MD = Path(__file__).resolve().parent / "users.md"


class UserManager:
    def __init__(self, filepath: Path = DEFAULT_USERS_MD, datastore: Datastore | None = None):
        self.filepath = filepath
        self.store = datastore or Datastore(md_path=filepath)

    @property
    def users(self) -> dict[int, dict]:
        profiles = {}
        for summary in self.store.get_all_users_summary():
            uid = summary["user_id"]
            p = self.store.get_user_profile(uid)
            if p:
                profiles[uid] = p
        return profiles

    def load(self):
        if self.filepath.exists():
            self.store.import_from_markdown(self.filepath)

    def save(self):
        self.store.export_to_markdown(self.filepath)

    def find_user_id_by_name(self, name: str) -> int | None:
        return self.store.find_user_id_by_name(name)

    def get_profile(self, user_id: int) -> dict | None:
        return self.store.get_user_profile(user_id)

    def get_summary_prompt(self, user_id: int, username: str) -> str:
        profile = self.store.get_user_profile(user_id)
        if not profile or not profile.get("facts"):
            return ""

        role = profile.get("role", "Server Member")
        facts = profile.get("facts", [])
        facts_preview = "; ".join(facts[:10])
        return f"[Memory notes on {username} ({role}) - subject to change: {facts_preview}]"

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
        actual_id = speaker_id if speaker_id is not None else (user_id or 0)
        actual_name = (
            speaker_name if speaker_name is not None else (username or f"User_{actual_id}")
        )

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

            target_name = u_match.group(1).strip() if u_match else actual_name
            category = c_match.group(1).strip().lower() if c_match else "general"

            if target_name.lower() in [actual_name.lower(), "me", "you", "speaker", "user", "self"]:
                target_uid = actual_id
                final_target_name = actual_name
            else:
                found_id = self.find_user_id_by_name(target_name)
                if found_id:
                    target_uid = found_id
                    final_target_name = target_name
                else:
                    target_uid = generate_deterministic_id(target_name)
                    final_target_name = target_name

            raw_facts = re.split(r"[\n;]+", content)
            inserted = self.store.add_facts(
                user_id=target_uid,
                username=final_target_name,
                facts=raw_facts,
                category=category,
            )
            for f in inserted:
                recorded.append(f"{final_target_name}: {f}")

        # Strip memory tags from user-facing text
        cleaned_text = tag_pat.sub("", raw_output).strip()
        cleaned_text = re.sub(
            r"<(?:remember|note)\b[^>]*\/?>", "", cleaned_text, flags=re.IGNORECASE
        ).strip()
        return recorded, cleaned_text

    def get_user_display_card(self, user_id: int, display_name: str) -> str:
        profile = self.store.get_user_profile(user_id)
        if not profile or not profile.get("facts"):
            return f"**{display_name}**: No specific memory notes recorded yet."

        facts = profile.get("facts", [])
        role = profile.get("role", "Server Member")
        lines = [f"**{display_name}** ({role}):"]
        for f in facts:
            lines.append(f"• {f}")
        return "\n".join(lines)

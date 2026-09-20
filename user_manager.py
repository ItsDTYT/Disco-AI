import logging
import re
from pathlib import Path

from obsidian_vault import ObsidianVault, UserNote, generate_deterministic_id

logger = logging.getLogger("DiscoUserManager")

DEFAULT_VAULT_DIR = Path(__file__).resolve().parent / "vault"
LEGACY_USERS_MD = Path(__file__).resolve().parent / "users.md"
LEGACY_EXAMPLE_MD = Path(__file__).resolve().parent / "users.example.md"


class UserManager:
    def __init__(self, vault_dir: Path | str = DEFAULT_VAULT_DIR):
        self.vault = ObsidianVault(vault_dir)
        self._bootstrap_if_empty()

    def _bootstrap_if_empty(self) -> None:
        if not self.vault.get_all_users():
            if LEGACY_USERS_MD.exists():
                logger.info("Migrating legacy memories from users.md into Obsidian Vault...")
                self.vault.import_from_legacy_markdown(LEGACY_USERS_MD)
            elif LEGACY_EXAMPLE_MD.exists():
                logger.info("Seeding initial Obsidian Vault profiles from users.example.md...")
                self.vault.import_from_legacy_markdown(LEGACY_EXAMPLE_MD)

    def get_profile(self, user_id: int) -> UserNote | None:
        return self.vault.get_user_note(user_id)

    def get_summary_prompt(self, user_id: int, username: str) -> str:
        note = self.vault.get_user_note(user_id)
        if not note or not note.facts:
            return ""

        facts_preview = "; ".join(f.content for f in note.facts[:10])
        return f"[Memory notes on {username} ({note.role}) - subject to change: {facts_preview}]"

    def add_facts(
        self,
        user_id: int,
        username: str,
        display_name: str,
        new_facts: list[str],
        role: str | None = None,
        category: str = "general",
    ) -> list[str]:
        return self.vault.add_facts(
            user_id=user_id,
            username=username,
            display_name=display_name,
            facts=new_facts,
            category=category,
            role=role,
        )

    def clear_user_facts(self, user_id: int) -> bool:
        return self.vault.clear_user_facts(user_id)

    def find_user_id_by_name(self, name: str) -> int | None:
        return self.vault.find_user_id_by_name(name)

    def process_autonomous_remember_tags(
        self,
        raw_output: str,
        speaker_id: int,
        speaker_name: str,
        display_name: str | None = None,
    ) -> tuple[list[str], str]:
        actual_display = display_name or speaker_name
        tag_pattern = re.compile(
            r"<(?:remember|note)(?:\s+([^>]+))?>([\s\S]*?)</(?:remember|note)>",
            re.IGNORECASE,
        )
        attr_pattern = re.compile(
            r"(?:user|speaker|for|target|about|person)=['\"]?([^'\"\s>]+)['\"]?",
            re.IGNORECASE,
        )
        cat_pattern = re.compile(
            r"(?:cat|category|type)=['\"]?([^'\"\s>]+)['\"]?",
            re.IGNORECASE,
        )

        recorded: list[str] = []

        for attrs_str, content in tag_pattern.findall(raw_output):
            attrs = attrs_str or ""
            u_match = attr_pattern.search(attrs)
            c_match = cat_pattern.search(attrs)

            target_name = u_match.group(1).strip() if u_match else actual_display
            category = c_match.group(1).strip().lower() if c_match else "general"

            if target_name.lower() in [actual_display.lower(), speaker_name.lower(), "me", "you", "speaker", "user", "self"]:
                target_uid = speaker_id
                target_user = speaker_name
                target_disp = actual_display
            else:
                found_id = self.find_user_id_by_name(target_name)
                if found_id:
                    target_uid = found_id
                    existing = self.vault.get_user_note(found_id)
                    target_user = existing.username if existing else target_name.lower().replace(" ", "_")
                    target_disp = existing.display_name if existing else target_name
                else:
                    target_uid = generate_deterministic_id(target_name)
                    target_user = target_name.lower().replace(" ", "_")
                    target_disp = target_name

            raw_facts = [f.strip() for f in re.split(r"[\n;]+", content) if f.strip()]
            inserted = self.vault.add_facts(
                user_id=target_uid,
                username=target_user,
                display_name=target_disp,
                facts=raw_facts,
                category=category,
            )
            for f in inserted:
                recorded.append(f"{target_disp}: {f}")

        cleaned_text = tag_pattern.sub("", raw_output).strip()
        cleaned_text = re.sub(r"<(?:remember|note)\b[^>]*\/?>", "", cleaned_text, flags=re.IGNORECASE).strip()
        return recorded, cleaned_text

    def get_user_display_card(self, user_id: int, display_name: str) -> str:
        note = self.vault.get_user_note(user_id)
        if not note or not note.facts:
            return f"**{display_name}**: No specific memory notes recorded yet in Obsidian Vault."

        lines = [f"**{display_name}** (`@{note.username}` | {note.role}):"]
        for fact in note.facts:
            lines.append(f"• {fact.content}")
        return "\n".join(lines)

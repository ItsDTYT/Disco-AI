import asyncio
import datetime
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord

from PIL import Image

from bot import (
    extract_user_profile,
    is_vision_model_error,
    resolve_discord_entities,
)
from media_utils import (
    MediaPayload,
    encode_pil_image_to_base64_jpeg,
    extract_gif_frames,
)
from obsidian_vault import ObsidianVault, UserFact, UserNote
from user_manager import UserManager


class TestObsidianVault(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="disco_vault_test_"))
        self.vault = ObsidianVault(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_and_read_user_note(self):
        note = self.vault.get_or_create_user(
            user_id=123456789,
            username="testuser",
            display_name="Test User",
            role="Moderator",
        )
        self.assertEqual(note.user_id, 123456789)
        self.assertEqual(note.username, "testuser")
        self.assertEqual(note.display_name, "Test User")
        self.assertEqual(note.role, "Moderator")

        # Reload from disk into fresh vault instance
        new_vault = ObsidianVault(self.temp_dir)
        loaded = new_vault.get_user_note(123456789)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.username, "testuser")
        self.assertEqual(loaded.role, "Moderator")

    def test_add_and_clear_facts(self):
        added = self.vault.add_facts(
            user_id=987654321,
            username="factuser",
            display_name="Fact User",
            facts=["Plays Minecraft on weekends", "Prefers dark mode"],
            category="gaming",
        )
        self.assertEqual(len(added), 2)

        # Check in memory and on disk
        note = self.vault.get_user_note(987654321)
        self.assertEqual(len(note.facts), 2)
        self.assertEqual(note.facts[0].content, "Plays Minecraft on weekends")
        self.assertEqual(note.facts[0].category, "gaming")

        # Verify Index dashboard exists
        index_path = self.temp_dir / "Index.md"
        self.assertTrue(index_path.exists())
        index_content = index_path.read_text(encoding="utf-8")
        self.assertIn("Fact User", index_content)
        self.assertIn("987654321", index_content)

        # Clear facts
        self.vault.clear_user_facts(987654321)
        refreshed = self.vault.get_user_note(987654321)
        self.assertEqual(len(refreshed.facts), 0)


class TestUserManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="disco_um_test_"))
        self.um = UserManager(vault_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_autonomous_remember_tags(self):
        raw_ai_text = (
            "Hey there! <remember>Loves Python and Rust</remember> "
            "I will remember that. Also <remember user='Bob'>Works as a dev</remember>!"
        )
        recorded, cleaned = self.um.process_autonomous_remember_tags(
            raw_output=raw_ai_text,
            speaker_id=111,
            speaker_name="alice",
            display_name="Alice",
        )
        self.assertEqual(len(recorded), 2)
        self.assertNotIn("<remember>", cleaned)
        self.assertIn("Alice: Loves Python and Rust", recorded)
        self.assertIn("Bob: Works as a dev", recorded)

        # Check Alice summary prompt
        summary = self.um.get_summary_prompt(111, "Alice")
        self.assertIn("Loves Python and Rust", summary)


class TestMediaUtils(unittest.TestCase):
    def test_pil_image_encoding(self):
        img = Image.new("RGB", (200, 200), color="blue")
        uri = encode_pil_image_to_base64_jpeg(img)
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))

    def test_gif_frame_extraction(self):
        frames = [Image.new("RGB", (100, 100), color=c) for c in ["red", "green", "blue"]]
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
        gif_bytes = buf.getvalue()

        extracted = extract_gif_frames(gif_bytes, max_frames=3)
        self.assertGreaterEqual(len(extracted), 1)
        self.assertTrue(all(f.startswith("data:image/jpeg;base64,") for f in extracted))

    def test_media_payload_dataclass(self):
        payload = MediaPayload(
            visual_blocks=[{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,123"}}],
            descriptions=["[Attached Image: pic.png]"],
        )
        self.assertTrue(payload.has_visuals)
        self.assertEqual(payload.summary_text, "[Attached Image: pic.png]")


class TestBotLogic(unittest.TestCase):
    def test_entity_resolution(self):
        mock_client = MagicMock()
        mock_client.user.id = 999999

        mock_msg = MagicMock()
        mock_msg.guild = MagicMock()

        # Mock member
        mock_member = MagicMock()
        mock_member.id = 12345
        mock_member.display_name = "Charlie"
        mock_msg.guild.get_member.side_effect = lambda uid: mock_member if uid == 12345 else None
        mock_msg.mentions = [mock_member]

        # Mock role
        mock_role = MagicMock()
        mock_role.name = "Admins"
        mock_msg.guild.get_role.side_effect = lambda rid: mock_role if rid == 67890 else None

        # Mock channel
        mock_channel = MagicMock()
        mock_channel.name = "general"
        mock_msg.guild.get_channel.side_effect = lambda cid: mock_channel if cid == 55555 else None

        input_text = "Hey <@12345> and <@&67890>, check <#55555>! <:cat_nod:88888> <a:dancing:77777>"
        resolved, pings = resolve_discord_entities(input_text, mock_msg, mock_client, "Disco")

        self.assertIn("@Charlie", resolved)
        self.assertIn("@Admins", resolved)
        self.assertIn("#general", resolved)
        self.assertIn(":cat_nod:", resolved)
        self.assertIn(":dancing:", resolved)
        self.assertIn("@Charlie", pings)
        self.assertIn("@Admins", pings)

    def test_extract_user_profile(self):
        mock_user = MagicMock(spec=discord.Member)
        mock_user.id = 897711166967664690
        mock_user.name = "itsdt"
        mock_user.display_name = "DT"
        mock_user.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=730)
        mock_user.joined_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)
        
        role_mock = MagicMock()
        role_mock.name = "Creator"
        mock_user.roles = [role_mock]
        mock_user.status = "online"
        
        act_mock = MagicMock()
        act_mock.name = "Cyberpunk"
        act_mock.type.name = "playing"
        mock_user.activities = [act_mock]

        dossier = extract_user_profile(mock_user, owner_id=897711166967664690)
        self.assertTrue(dossier.is_owner)
        self.assertIn("Creator", dossier.roles)
        self.assertIn("~2 years ago", dossier.account_age)
        
        ctx = dossier.to_prompt_context()
        self.assertIn("Rank: Bot Owner", ctx)
        self.assertIn("Creator", ctx)
        self.assertIn("Cyberpunk", ctx)

    def test_vision_model_error_detection(self):
        self.assertTrue(is_vision_model_error("LLM API error (400): Model does not support image_url input"))
        self.assertTrue(is_vision_model_error("invalid_request_error: vision is not enabled for model qwen3.5-4b"))
        self.assertFalse(is_vision_model_error("Connection timed out after 180s"))


if __name__ == "__main__":
    unittest.main()

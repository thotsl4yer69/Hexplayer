import json
import tempfile
import unittest
from pathlib import Path

from hexplayer import TileRegistry, legacy_uid_alias, normalise_card, uid_to_string


class HexPlayerCoreTests(unittest.TestCase):
    def test_uid_format_and_legacy_bcc(self):
        self.assertEqual(uid_to_string([0x04, 0xA1, 0x00, 0xFF]), "04-A1-00-FF")
        self.assertEqual(legacy_uid_alias("04-A1-00-FF"), "04-A1-00-FF-5A")

    def test_v1_registry_is_read_and_legacy_uid_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tiles.json"
            path.write_text(json.dumps({"04-A1-00-FF-5A": "spotify:album:abc"}))
            registry = TileRegistry(path)
            card = registry.get("04-A1-00-FF")
            self.assertEqual(card["action"]["uri"], "spotify:album:abc")

    def test_registry_writes_v2(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tiles.json"
            registry = TileRegistry(path)
            registry.upsert("01-02-03-04", {"name": "Test", "action": {"type": "ha_event", "event_type": "hex_test"}})
            data = json.loads(path.read_text())
            self.assertEqual(data["version"], 2)
            self.assertEqual(data["tiles"]["01-02-03-04"]["action"]["event_type"], "hex_test")

    def test_card_validation(self):
        card = normalise_card({"name": "Kitchen", "action": {"type": "ha_media", "entity_id": "media_player.kitchen", "media_content_id": "spotify:track:x"}})
        self.assertEqual(card["action"]["type"], "ha_media")
        with self.assertRaises(ValueError):
            normalise_card({"action": {"type": "ha_media", "entity_id": "light.kitchen", "media_content_id": "x"}})


if __name__ == "__main__":
    unittest.main()

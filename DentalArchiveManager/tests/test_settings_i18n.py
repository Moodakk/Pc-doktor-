from __future__ import annotations

import unittest
from unittest import mock

from dental_archive import i18n, settings


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_merge(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(settings, "settings_directory", return_value=Path(directory)):
                self.assertEqual(settings.load_settings(), {})
                settings.save_settings({"language": "en"})
                settings.save_settings({"last_destination": "D:/archive"})
                stored = settings.load_settings()
                self.assertEqual(stored["language"], "en")
                self.assertEqual(stored["last_destination"], "D:/archive")

    def test_load_ignores_corrupt_file(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "settings.json").write_text("{broken", encoding="utf-8")
            with mock.patch.object(settings, "settings_directory", return_value=path):
                self.assertEqual(settings.load_settings(), {})


class I18nTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language("uk", persist=False)

    def test_translation_switch(self) -> None:
        i18n.set_language("uk", persist=False)
        self.assertEqual(i18n.tr("ui.scan"), "Сканувати")
        i18n.set_language("en", persist=False)
        self.assertEqual(i18n.tr("ui.scan"), "Scan")

    def test_parameters_and_missing_key(self) -> None:
        i18n.set_language("en", persist=False)
        self.assertIn("3", i18n.tr("ui.status.walk", count=3, name="x"))
        self.assertEqual(i18n.tr("no.such.key"), "no.such.key")

    def test_unsupported_language_rejected(self) -> None:
        with self.assertRaises(ValueError):
            i18n.set_language("de", persist=False)

    def test_every_key_has_both_languages(self) -> None:
        for key, value in i18n._TABLE.items():
            self.assertEqual(len(value), 2, key)
            self.assertTrue(value[0], key)
            self.assertTrue(value[1], key)


if __name__ == "__main__":
    unittest.main()

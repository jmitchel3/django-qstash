from __future__ import annotations

from django.test import TestCase
from django.test import override_settings

import django_qstash.settings
from django_qstash.settings import qstash_settings


class SettingsTestCase(TestCase):
    def test_default_webhook_path(self):
        """The default webhook path is exposed when not overridden."""
        self.assertEqual(qstash_settings.DJANGO_QSTASH_WEBHOOK_PATH, "/qstash/webhook/")

    def test_module_level_lazy_access(self):
        """Module-level attribute access stays available for back-compat."""
        self.assertEqual(
            django_qstash.settings.DJANGO_QSTASH_WEBHOOK_PATH, "/qstash/webhook/"
        )

    def test_unknown_setting_raises(self):
        """Accessing an unknown setting raises AttributeError."""
        with self.assertRaises(AttributeError):
            qstash_settings.NOT_A_REAL_SETTING

    @override_settings(DJANGO_QSTASH_WEBHOOK_PATH="/custom/webhook/path/")
    def test_override_settings_takes_effect_without_reload(self):
        """Lazy access means @override_settings is reflected immediately."""
        self.assertEqual(
            qstash_settings.DJANGO_QSTASH_WEBHOOK_PATH, "/custom/webhook/path/"
        )
        self.assertEqual(
            django_qstash.settings.DJANGO_QSTASH_WEBHOOK_PATH, "/custom/webhook/path/"
        )

    def test_eager_default_is_false(self):
        """ALWAYS_EAGER defaults to False so production behavior is unchanged."""
        self.assertFalse(qstash_settings.DJANGO_QSTASH_ALWAYS_EAGER)

    @override_settings(DJANGO_QSTASH_ALWAYS_EAGER=True)
    def test_eager_setting_reflected(self):
        self.assertTrue(qstash_settings.DJANGO_QSTASH_ALWAYS_EAGER)

"""Host-SDK credential/billing boundaries; no private token discovery."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from .inventory import load_catalog


class CredentialBoundaries(unittest.TestCase):
    def catalog(self, provider='openai-codex', **changes):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            (home / 'auth.json').write_text('invalid-json-must-not-be-read')
            metadata = {provider: {'models': {'small': {
                'modalities': {'input': ['text'], 'output': ['text']},
                'limit': {'context': 16000, 'output': 2048}, 'cost': {'input': 1, 'output': 1}}}}}
            (home / 'models_dev_cache.json').write_text(json.dumps(metadata))
            row = {'slug': provider, 'authenticated': True, 'models': ['small'], 'source': 'hermes'}
            row.update(changes)
            with (
                patch('hermes_constants.get_hermes_home', return_value=home),
                patch('hermes_cli.config.load_config_readonly', return_value={}),
                patch('hermes_cli.inventory.build_models_payload', return_value={'providers': [row]}),
            ):
                return load_catalog()

    def test_positive_host_authenticated_inventory_is_selectable(self):
        self.assertEqual(self.catalog()[0]['model'], 'small')

    def test_absent_host_billing_provenance_is_unknown_even_with_api_price_metadata(self):
        for provider in ('anthropic', 'openai', 'google', 'openai-codex'):
            with self.subTest(provider=provider):
                row = self.catalog(provider)[0]
                self.assertEqual(row['billing'], 'unknown')
                self.assertFalse(row['priced'])

    def test_environment_key_presence_cannot_certify_or_change_host_billing(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture-key-not-a-credential'}):
            self.assertEqual(self.catalog('anthropic')[0]['billing'], 'unknown')

    def test_only_explicit_host_usd_billing_provenance_allows_usd_estimate(self):
        row = self.catalog('anthropic', billing='usd')[0]
        self.assertEqual(row['billing'], 'usd')
        self.assertTrue(row['priced'])

    def test_host_unavailable_auth_and_unbound_catalog_sources_stay_closed(self):
        for changes in ({'authenticated': False}, {'authenticated': None},
                        {'source': 'canonical'}, {'source': 'configured-current'},
                        {'native_catalog_empty': True}):
            with self.subTest(changes=changes):
                self.assertEqual(self.catalog(**changes), [])

    def test_provider_aliases_are_normalized_without_touching_credentials(self):
        self.assertEqual(self.catalog('openai-api')[0]['provider'], 'openai')
        self.assertEqual(self.catalog('gemini')[0]['provider'], 'google')
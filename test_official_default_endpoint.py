"""Public host inventory owns endpoint/auth decisions; no private client bypass."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

OFFICIAL = 'https://chatgpt.com/backend-api/codex'


class OfficialDefaultEndpointTests(unittest.TestCase):
    def catalog(self, model_config, **changes):
        from .inventory import load_catalog
        row = {'slug': 'openai-codex', 'authenticated': True, 'models': ['fixture-small'], 'source': 'hermes'}
        row.update(changes)
        with (
            TemporaryDirectory() as directory,
            patch('hermes_constants.get_hermes_home', return_value=Path(directory)),
            patch('hermes_cli.config.load_config_readonly', return_value={'model': model_config}),
            patch('hermes_cli.inventory.build_models_payload', return_value={'providers': [row]}) as build,
        ):
            rows = load_catalog()
            self.assertEqual(build.call_args.args[0].current_base_url, model_config.get('base_url', ''))
            return rows

    def test_official_default_base_url_keeps_host_approved_provider_catalog(self):
        rows = self.catalog({'provider': 'openai-codex', 'base_url': OFFICIAL})
        self.assertEqual([(r['provider'], r['model']) for r in rows], [('openai-codex', 'fixture-small')])

    def test_official_default_trailing_slash_variant_is_not_locally_vetoed(self):
        self.assertTrue(self.catalog({'provider': 'openai-codex', 'base_url': OFFICIAL + '/'}))

    def test_custom_user_defined_inventory_row_stays_excluded(self):
        self.assertEqual(self.catalog({'provider': 'openai-codex'}, is_user_defined=True), [])

    def test_custom_current_and_ambiguous_canonical_sources_stay_excluded(self):
        config = {'provider': 'openai-codex', 'base_url': 'https://fixture-custom.invalid/v1'}
        for flags in ({'source': 'configured-current'}, {'source': 'canonical'},
                      {'is_user_defined': True}, {'native_catalog_empty': True}):
            with self.subTest(flags=flags):
                self.assertEqual(self.catalog(config, **flags), [])

    def test_host_rejected_authentication_stays_excluded(self):
        self.assertEqual(self.catalog({'provider': 'openai-codex'}, authenticated=False), [])

    def test_missing_authentication_contract_stays_excluded(self):
        self.assertEqual(self.catalog({'provider': 'openai-codex'}, authenticated=None), [])

    def test_models_explicitly_locked_by_host_stay_excluded(self):
        self.assertEqual(self.catalog({'provider': 'openai-codex'}, unavailable_models=['fixture-small']), [])


if __name__ == '__main__':
    unittest.main()

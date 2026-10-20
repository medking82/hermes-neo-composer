"""Real public inventory builder contract, offline account-discovery fixture only.

Do not replace build_models_payload: authenticated metadata is option-dependent.
No credential discovery, provider request, or production configuration is used.
"""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class PublicCatalogContractTests(unittest.TestCase):
    def catalog(self, **changes):
        from .sdk_catalog import load_catalog
        from hermes_cli import inventory

        # Native discovery returns approved built-ins without picker metadata.
        row = {'slug': 'openai-codex', 'models': ['gpt-6-luna'], 'source': 'hermes'}
        row.update(changes)
        with (
            TemporaryDirectory() as directory,
            patch('hermes_constants.get_hermes_home', return_value=Path(directory)),
            patch('hermes_cli.config.load_config_readonly', return_value={
                'model': {'provider': 'openai-codex', 'default': 'fixture-main'}}),
            patch('hermes_cli.model_switch.list_authenticated_providers',
                  side_effect=lambda **kwargs: [copy.deepcopy(row)]),
            patch.object(inventory, '_local_runtime_row', return_value=None),
            patch.object(inventory, '_moa_provider_row', return_value=None),
        ):
            return load_catalog()

    def test_real_builder_metadata_keeps_host_approved_builtin_model_available(self):
        self.assertEqual([(row['provider'], row['model']) for row in self.catalog()],
                         [('openai-codex', 'gpt-6-luna')])

    def test_real_builder_does_not_weaken_existing_identity_or_availability_filters(self):
        for changes in (
            {'authenticated': False}, {'authenticated': None},
            {'source': 'canonical'}, {'source': 'configured-current'},
            {'is_user_defined': True}, {'native_catalog_empty': True},
            {'unavailable_models': ['gpt-6-luna']},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.catalog(**changes), [])

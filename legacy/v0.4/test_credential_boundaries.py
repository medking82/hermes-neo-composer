"""Final authorized boundary fixes; synthetic credentials, no network."""
import json
import os
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from .inventory import billing_kind, load_catalog

class CredentialBoundaries(unittest.TestCase):
    def catalog(self, provider, env, *, auth=None, fingerprint='owner', external=False, root_oauth=False, inherited=None):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            home = Path(directory)
            external_dir = home / ('relocated' if external == 'relocated' else '.claude')
            if external:
                external_dir.mkdir()
                (external_dir / '.credentials.json').write_text('{}')
            if external == 'relocated': env = {**env, 'CLAUDE_CONFIG_DIR': str(external_dir)}
            root_file = home / 'root-oauth.json'
            if root_oauth: root_file.write_text('{}')
            root_auth = home / 'root-auth.json'
            if inherited: root_auth.write_text(json.dumps(inherited))
            stack.enter_context(patch('agent.anthropic_credentials._root_hermes_oauth_file', return_value=root_file if root_oauth else None))
            stack.enter_context(patch('hermes_cli.auth._global_auth_file_path', return_value=root_auth if inherited else None))
            stack.enter_context(patch('pathlib.Path.home', return_value=home))
            stack.enter_context(patch('hermes_constants.get_hermes_home', return_value=home))
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            stack.enter_context(patch('hermes_cli.config.get_env_value_prefer_dotenv', side_effect=lambda name: env.get(name, '')))
            stack.enter_context(patch('hermes_cli.config.load_config_readonly', return_value={}))
            stack.enter_context(patch('hermes_cli.models._load_provider_models_cache', return_value={provider:{'fp':'owner','at':time.time(),'models':['small']}}))
            stack.enter_context(patch('hermes_cli.models._credential_fingerprint', side_effect=fingerprint if callable(fingerprint) else None, return_value=fingerprint if not callable(fingerprint) else None))
            stack.enter_context(patch('hermes_cli.auth._load_auth_store', return_value=auth or {}))
            return load_catalog()

    def test_positive_api_controls_and_unbound_borrowed_sources(self):
        for provider, env in [('anthropic', {'ANTHROPIC_API_KEY':'sk-ant-api-synthetic'}), ('anthropic', {'ANTHROPIC_TOKEN':'sk-ant-api-synthetic'}), ('openai', {'OPENAI_API_KEY':'synthetic'}), ('google', {'GEMINI_API_KEY':'synthetic'})]:
            self.assertEqual(self.catalog(provider,env)[0]['billing'],'usd')
        env={'ANTHROPIC_API_KEY':'sk-ant-api-synthetic'}
        self.assertEqual(self.catalog('anthropic',env,root_oauth=True),[])
        self.assertEqual(self.catalog('anthropic',env,external='relocated'),[])
        self.assertEqual(self.catalog('anthropic',env,inherited={'credential_pool':{'anthropic':[{'source':'hermes_pkce'}]}}),[])
        self.assertEqual(self.catalog('anthropic',{},external=True),[])

    def test_oauth_and_unknown_anthropic_key_formats_cannot_auto_rank(self):
        for token in ['eyJsynthetic', 'cc-synthetic', 'sk-ant-oat-synthetic', 'unknown']:
            self.assertEqual(billing_kind('anthropic',token,False),'unknown')
        self.assertEqual(billing_kind('anthropic','sk-ant-api-synthetic',False),'usd')

    def test_secondary_env_and_external_oauth_are_not_dollar_billed(self):
        env={'ANTHROPIC_API_KEY':'sk-ant-api-synthetic','CLAUDE_CODE_OAUTH_TOKEN':'eyJsynthetic'}
        self.assertEqual(self.catalog('anthropic',env)[0]['billing'],'unknown')
        del env['CLAUDE_CODE_OAUTH_TOKEN']
        self.assertEqual(self.catalog('anthropic',env,external=True)[0]['billing'],'unknown')

    def test_canonical_pool_alias_counts_as_other_credential(self):
        rows=self.catalog('openai',{'OPENAI_API_KEY':'synthetic'},auth={'credential_pool':{'openai-api':[{}]}})
        self.assertEqual(rows[0]['billing'],'unknown')
        rows=self.catalog('google',{'GEMINI_API_KEY':'synthetic'},auth={'providers':{'gemini':{'account':'synthetic'}}})
        self.assertEqual(rows[0]['billing'],'unknown')

    def test_legacy_alias_fingerprint_cannot_certify_the_account(self):
        for provider,key,canonical in [('openai','OPENAI_API_KEY','openai-api'),('google','GEMINI_API_KEY','gemini')]:
            def fp(name): return 'new-account' if name==canonical else 'owner'
            self.assertEqual(self.catalog(provider,{key:'synthetic'},fingerprint=fp),[])

    def test_pinned_host_canonical_fingerprint_changes_with_key(self):
        from hermes_cli.models import _credential_fingerprint
        with TemporaryDirectory() as d, patch('hermes_constants.get_hermes_home',return_value=Path(d)):
            for provider,var in [('openai-api','OPENAI_API_KEY'),('gemini','GEMINI_API_KEY')]:
                with patch.dict(os.environ,{var:'synthetic-a'}): a=_credential_fingerprint(provider)
                with patch.dict(os.environ,{var:'synthetic-b'}): b=_credential_fingerprint(provider)
                self.assertNotEqual(a,b)

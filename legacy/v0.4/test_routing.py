import importlib
import unittest


class RoutingTests(unittest.TestCase):
    def test_automatic_uses_verified_cost_and_explicit_override_wins(self):
        try:
            routing = importlib.import_module(__package__ + '.routing')
        except ModuleNotFoundError:
            routing = None
        self.assertIsNotNone(routing, 'Cost-aware prediction routing is not implemented')
        settings = {'enabled': True, 'model': '', 'fallback': '', 'providers': ['api']}
        def candidate(model, cost, **extra):
            return dict(provider='api', model=model, available=True, text=True,
                        input_cost=cost, output_cost=cost, billing='usd', priced=True,
                        context=16000, max_output=2048, **extra)
        rows = [candidate('large', 10), candidate('small', 1)]
        self.assertEqual(routing.select_route(settings, rows)['route']['model'], 'small')
        self.assertEqual(routing.select_route({**settings, 'model': 'api/large'}, rows)['route']['model'], 'large')

    def test_unknown_subscription_and_stale_routes_fail_closed(self):
        from .routing import select_route
        settings = {'enabled': True, 'model': '', 'fallback': '', 'providers': ['subscription']}
        row = dict(provider='subscription', model='choice', available=True, text=True,
                   billing='subscription', priced=False, input_cost=0, output_cost=0,
                   context=16000, max_output=2048)
        self.assertIsNone(select_route(settings, [row])['route'])
        self.assertEqual(select_route({**settings, 'fallback': 'subscription/choice'}, [row])['route'], row)
        self.assertIsNone(select_route({**settings, 'model': 'subscription/missing'}, [row])['route'])
        self.assertIsNone(select_route({**settings, 'enabled': False, 'model': 'subscription/choice'}, [row])['route'])
        self.assertIsNone(select_route({**settings, 'fallback': 'subscription/choice'}, [{**row, 'available': False}])['route'])

    def test_settings_are_validated_and_persisted_without_main_config(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        try:
            settings = importlib.import_module(__package__ + '.settings')
        except ModuleNotFoundError:
            settings = None
        self.assertIsNotNone(settings, 'Profile-local prediction settings are missing')
        with TemporaryDirectory() as folder:
            home = Path(folder)
            home.joinpath('config.yaml').write_text('model: do-not-change')
            value = {'enabled': True, 'providers': ['api'], 'model': '', 'fallback': 'api/small'}
            settings.save_settings(home, value)
            self.assertEqual(settings.load_settings(home), value)
            self.assertEqual(home.joinpath('config.yaml').read_text(), 'model: do-not-change')
            for invalid in ({**value, 'api_key': 'no-secrets'}, {**value, 'enabled': 'true'}, {**value, 'providers': ['../other']}):
                with self.assertRaises(ValueError):
                    settings.save_settings(home, invalid)
            self.assertEqual(settings.load_settings(home), value)

    def test_inventory_rejects_stale_foreign_and_unknown_price_rows(self):
        try:
            inventory = importlib.import_module(__package__ + '.inventory')
        except ModuleNotFoundError:
            inventory = None
        self.assertIsNotNone(inventory, 'Verified account inventory is missing')
        data = {'provider': 'api', 'fp': 'owner', 'at': 100, 'models': ['small']}
        meta = {'small': {'modalities': {'input': ['text'], 'output': ['text']}, 'limit': {'context': 16000, 'output': 2048}, 'cost': {'input': 1, 'output': 2}}}
        rows = inventory.catalog_rows('api', data, 'owner', meta, now=101, price_fresh=True, billing='usd')
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['priced'])
        for entry in ({**data, 'at': -100000}, {**data, 'fp': 'other'}, {**data, 'fallback': True}):
            self.assertEqual(inventory.catalog_rows('api', entry, 'owner', meta, now=101, price_fresh=True, billing='usd'), [])
        unknown = inventory.catalog_rows('api', data, 'owner', {'small': {}}, now=101, price_fresh=True, billing='usd')
        self.assertFalse(unknown[0]['priced'])
        quota = inventory.catalog_rows('api', data, 'owner', meta, now=101, price_fresh=True, billing='subscription')
        self.assertFalse(quota[0]['priced'])


if __name__ == '__main__':
    unittest.main()

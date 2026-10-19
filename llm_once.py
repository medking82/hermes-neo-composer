"""Compatibility import for the public host-SDK prediction adapter.

One logical SDK request may use host-managed retries and configured fallbacks,
as approved by the operator. Private planning, credential reads and byte pins
are retired. A profile-bound public SDK context must be supplied explicitly.
"""
from .sdk_llm import PREDICTION_EFFORT, complete, validate_context


def validate_host(context=None):
    return validate_context(context)


def prediction_plan():
    from hermes_constants import get_hermes_home
    from .settings import load_settings
    from .sdk_catalog import load_catalog
    from .routing import select_route
    settings = load_settings(get_hermes_home())
    return {**select_route(settings, load_catalog() if settings['enabled'] else []), 'settings': settings}

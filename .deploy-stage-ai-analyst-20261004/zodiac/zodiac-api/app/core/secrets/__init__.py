"""
BridgeEDI Core — Secret resolution (PR2).

Centralized, pluggable providers. Never log resolved secret values.
"""
from .base import (
    SecretProvider,
    SecretResolutionError,
    SecretResolver,
    parse_secret_ref,
)
from .resolver import (
    CompositeSecretResolver,
    LiteralOnlyResolver,
    get_default_secret_resolver,
    reset_default_secret_resolver_for_tests,
)

__all__ = [
    "SecretProvider",
    "SecretResolver",
    "SecretResolutionError",
    "parse_secret_ref",
    "CompositeSecretResolver",
    "LiteralOnlyResolver",
    "get_default_secret_resolver",
    "reset_default_secret_resolver_for_tests",
]

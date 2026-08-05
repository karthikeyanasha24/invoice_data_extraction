"""
Phase 3 tests — Adapter Registry.

No DB and no network required. Run from zodiac-api:

  python -m unittest app.tests.test_adapter_registry -v
"""
from __future__ import annotations

import pathlib
import re
import tokenize
import unittest
from typing import Any, List

from app.adapters import (
    AdapterCapability,
    AdapterContext,
    AdapterNotRegisteredError,
    AdapterRegistry,
    AdapterStage,
    CountryAdapter,
    StageResult,
    ensure_builtin_adapters,
)
from app.adapters.registry import (
    AdapterAlreadyRegisteredError,
    AdapterRegistryError,
    normalize_country_code,
)


class FakeCountryAdapter(CountryAdapter):
    """A future country, added without touching the platform."""

    country_code = "india"
    display_name = "India — GST e-Invoice"
    supported_document_types = ("INVOICE",)

    def __init__(self, db: Any = None, config: Any = None):
        self.db = db
        self.config = config

    def capabilities(self) -> List[AdapterCapability]:
        return [AdapterCapability.PARSE]

    def parse(self, ctx): return StageResult.ok(AdapterStage.PARSE, {"ok": True})
    def validate(self, ctx): return StageResult.ok(AdapterStage.VALIDATE)
    def map(self, ctx): return StageResult.ok(AdapterStage.MAP)
    def apply_business_rules(self, ctx): return StageResult.ok(AdapterStage.BUSINESS_RULES)
    def transform(self, ctx): return StageResult.ok(AdapterStage.TRANSFORM)
    def format(self, ctx): return StageResult.ok(AdapterStage.FORMAT)
    async def submit(self, ctx): return StageResult.ok(AdapterStage.SUBMIT)
    def receive_confirmation(self, ctx, response=None): return StageResult.ok(AdapterStage.CONFIRMATION)


class NotAnAdapter:
    pass


class TestNormalization(unittest.TestCase):
    def test_normalizes_case_and_separators(self):
        self.assertEqual(normalize_country_code("MX-CFDI"), "mx_cfdi")
        self.assertEqual(normalize_country_code("  India "), "india")

    def test_rejects_empty(self):
        for bad in (None, "", "   "):
            with self.assertRaises(AdapterRegistryError):
                normalize_country_code(bad)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = AdapterRegistry()

    def test_register_and_resolve(self):
        self.registry.register("india", FakeCountryAdapter)
        adapter = self.registry.resolve("india")
        self.assertIsInstance(adapter, FakeCountryAdapter)

    def test_resolution_is_case_insensitive(self):
        self.registry.register("india", FakeCountryAdapter)
        self.assertIsInstance(self.registry.resolve("INDIA"), FakeCountryAdapter)

    def test_aliases_resolve_to_same_adapter(self):
        self.registry.register("india", FakeCountryAdapter, aliases=("in", "IND"))
        for code in ("india", "in", "ind"):
            self.assertIsInstance(self.registry.resolve(code), FakeCountryAdapter)

    def test_dependencies_are_injected(self):
        sentinel_db = object()
        sentinel_cfg = {"a": 1}
        self.registry.register("india", FakeCountryAdapter)
        adapter = self.registry.resolve("india", db=sentinel_db, config=sentinel_cfg)
        self.assertIs(adapter.db, sentinel_db)
        self.assertIs(adapter.config, sentinel_cfg)

    def test_each_resolve_returns_a_fresh_instance(self):
        self.registry.register("india", FakeCountryAdapter)
        self.assertIsNot(self.registry.resolve("india"), self.registry.resolve("india"))

    def test_unknown_country_raises_with_available_list(self):
        self.registry.register("india", FakeCountryAdapter)
        with self.assertRaises(AdapterNotRegisteredError) as cm:
            self.registry.resolve("atlantis")
        self.assertEqual(cm.exception.country_code, "atlantis")
        self.assertIn("india", cm.exception.available)

    def test_duplicate_registration_rejected_unless_replace(self):
        self.registry.register("india", FakeCountryAdapter)
        with self.assertRaises(AdapterAlreadyRegisteredError):
            self.registry.register("india", FakeCountryAdapter)
        self.registry.register("india", FakeCountryAdapter, replace=True)

    def test_factory_must_return_a_country_adapter(self):
        self.registry.register("atlantis", lambda **kw: NotAnAdapter())
        with self.assertRaises(AdapterRegistryError):
            self.registry.resolve("atlantis")

    def test_non_callable_factory_rejected(self):
        with self.assertRaises(AdapterRegistryError):
            self.registry.register("india", "not-callable")

    def test_unregister_removes_code_and_aliases(self):
        self.registry.register("india", FakeCountryAdapter, aliases=("in",))
        self.assertTrue(self.registry.unregister("india"))
        self.assertFalse(self.registry.is_registered("india"))
        self.assertFalse(self.registry.is_registered("in"))

    def test_describe_lists_metadata(self):
        self.registry.register("india", FakeCountryAdapter)
        catalog = self.registry.describe()
        self.assertEqual(catalog[0]["country_code"], "india")
        self.assertEqual(catalog[0]["capabilities"], ["parse"])

    def test_new_country_needs_no_platform_change(self):
        """Adding a country is registration only — the pipeline is untouched."""
        self.registry.register("india", FakeCountryAdapter)
        adapter = self.registry.resolve("india")
        ctx = AdapterContext(customer_id="acme", country_code="india")
        self.assertTrue(adapter.parse(ctx).success)


class TestBuiltinBootstrap(unittest.TestCase):
    def test_mx_cfdi_is_registered_with_aliases(self):
        reg = AdapterRegistry()
        ensure_builtin_adapters(reg)
        self.assertIn("mx_cfdi", reg.available())
        for alias in ("mx", "mexico", "cfdi", "MX"):
            self.assertTrue(reg.is_registered(alias), alias)

    def test_bootstrap_is_idempotent(self):
        reg = AdapterRegistry()
        ensure_builtin_adapters(reg)
        ensure_builtin_adapters(reg)
        self.assertEqual(reg.available(), ["mx_cfdi", "sample_gst"])

    def test_bootstrap_registers_both_builtin_adapters(self):
        reg = AdapterRegistry()
        ensure_builtin_adapters(reg)
        self.assertIn("mx_cfdi", reg.available())
        self.assertIn("sample_gst", reg.available())
        self.assertTrue(reg.is_registered("sample"))
        self.assertTrue(reg.is_registered("demo_gst"))

    def test_resolved_mx_adapter_implements_the_contract(self):
        reg = AdapterRegistry()
        ensure_builtin_adapters(reg)
        adapter = reg.resolve("mx", db=None)
        self.assertIsInstance(adapter, CountryAdapter)
        for method in (
            "parse", "validate", "map", "apply_business_rules", "transform",
            "format", "submit", "receive_confirmation", "update_erp",
            "generate_monitoring_event",
        ):
            self.assertTrue(callable(getattr(adapter, method)), method)


class TestNoCountryConditionals(unittest.TestCase):
    """Guards the architectural rule: no `if country == "MX"` in the platform."""

    PATTERN = re.compile(r"""country(_code)?\s*==\s*['"]""", re.IGNORECASE)

    @staticmethod
    def _code_lines(path: pathlib.Path):
        """Yield (lineno, source) with comments and string literals removed."""
        lines = {}
        with tokenize.open(path) as handle:
            for tok in tokenize.generate_tokens(handle.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                lines.setdefault(tok.start[0], []).append(tok.string)
        return sorted((no, " ".join(parts)) for no, parts in lines.items())

    def test_framework_contains_no_country_equality_checks(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        offenders = []
        for folder in ("adapters", "core"):
            for path in (root / folder).rglob("*.py"):
                for lineno, source in self._code_lines(path):
                    if self.PATTERN.search(source):
                        offenders.append(f"{path.name}:{lineno}: {source.strip()}")
        self.assertEqual(offenders, [], "Country conditionals found:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()

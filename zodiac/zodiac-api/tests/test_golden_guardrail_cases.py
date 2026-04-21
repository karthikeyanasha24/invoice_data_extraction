import json
from pathlib import Path

from app.api.adaptive_query import _schema_reference_violations, _sql_guardrail_violations


def test_golden_guardrail_cases_from_json() -> None:
    path = Path(__file__).resolve().parent / "golden_guardrail_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(cases, list) and cases, "golden_guardrail_cases.json must contain test cases"

    for case in cases:
        name = str(case.get("name") or "unnamed")
        q = str(case.get("question") or "")
        sql = str(case.get("sql") or "")

        business_v = _sql_guardrail_violations(q, sql)
        schema_v = _schema_reference_violations(sql)
        business_text = " | ".join(business_v)
        schema_text = " | ".join(schema_v)

        for must_contain in case.get("expect_violations_contains") or []:
            assert str(must_contain) in business_text, (
                f"[{name}] expected business violation containing '{must_contain}', "
                f"got: {business_text}"
            )

        for must_contain in case.get("expect_schema_violations_contains") or []:
            assert str(must_contain) in schema_text, (
                f"[{name}] expected schema violation containing '{must_contain}', "
                f"got: {schema_text}"
            )

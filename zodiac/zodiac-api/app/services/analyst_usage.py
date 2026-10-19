"""Provider-reported usage; configurable prices, conservative dispatch limits."""
from __future__ import annotations
import json
import os
from decimal import Decimal
from .investigation_budget import current_budget


class AnalystResourceLimit(ValueError):
    pass


def usage_summary():
    budget = current_budget()
    calls = (budget.diagnostics.get('model_usage') or []) if budget else []
    return {'calls': calls, **{key:sum(c.get(key, 0) for c in calls) for key in
        ('input_tokens','output_tokens','cached_tokens','cache_write_tokens','reasoning_tokens','total_tokens')},
        'models':sorted({c.get('model') for c in calls if c.get('model')}),
        'estimated_cost_usd': str(sum(Decimal(c['estimated_cost_usd']) for c in calls)) if calls and all(c.get('estimated_cost_usd') is not None for c in calls) else None,
        'pricing_complete':bool(calls) and all(c.get('estimated_cost_usd') is not None for c in calls),
        'usage_complete':all(c.get('usage_reported') for c in calls),
        'cost_basis':'configured model rates; excludes unpriced tool/provider fees'}


def model_limits(input, instructions='', tools=None, requested_output=8000, model=''):
    summary = usage_summary()
    if len(summary['calls']) >= int(os.getenv('AI_ANALYST_MAX_MODEL_CALLS', '16')):
        raise AnalystResourceLimit('Model-call budget reached; narrow the request or use the result drill-down')
    # Provider-reported tokens are the accounting authority. Prompt byte length is
    # not interchangeable with tokens and must not abort a finished SQL investigation.
    remaining = int(os.getenv('AI_ANALYST_MAX_TOTAL_TOKENS', '250000')) - summary['total_tokens']
    output = min(int(os.getenv('AI_ANALYST_MAX_OUTPUT_TOKENS', str(requested_output))), requested_output, max(0, remaining))
    if output < 512:
        raise AnalystResourceLimit('Token budget reached; start a narrower investigation')
    cap = os.getenv('AI_ANALYST_MAX_REQUEST_USD')
    if cap:
        prompt_bytes = len(json.dumps(
            {'input': input, 'instructions': instructions, 'tools': tools or []},
            default=str, ensure_ascii=False,
        ).encode('utf-8'))
        estimated = price(model, max(1, prompt_bytes // 4), output, 0, 0)
        if estimated is None or (summary['calls'] and not summary['pricing_complete']):
            raise AnalystResourceLimit('A dollar budget requires configured prices for every enabled model')
        spent = Decimal(summary['estimated_cost_usd'] or '0')
        if spent + Decimal(estimated) > Decimal(cap):
            raise AnalystResourceLimit('Estimated next call exceeds the request dollar budget')
    return max(512, output)


def _rate_card():
    from pathlib import Path
    card = {}
    path = Path(__file__).resolve().parents[1] / 'config' / 'analyst_model_rates.json'
    if path.exists():
        loaded = json.loads(path.read_text(encoding='utf-8'))
        card.update(loaded.get('models') or {})
    card.update(json.loads(os.getenv('AI_ANALYST_PRICING_JSON', '{}')))
    return card


def price(model, input_tokens, output_tokens, cached_tokens, cache_write_tokens):
    if model.startswith(('ollama/', 'groq-free/')):
        return '0'
    try:
        config = _rate_card().get(model)
        if not config or not config.get('version'):
            return None
        # Rates are per million tokens. Cache writes can have their own rate.
        if cached_tokens + cache_write_tokens > input_tokens:
            return None  # do not guess overlapping accounting semantics
        normal = input_tokens - cached_tokens - cache_write_tokens
        return str((Decimal(normal)*Decimal(str(config['input'])) + Decimal(output_tokens)*Decimal(str(config['output']))
            + Decimal(cached_tokens)*Decimal(str(config['cached_input']))
            + Decimal(cache_write_tokens)*Decimal(str(config.get('cache_write',config['input']))))/Decimal(1000000))
    except (ValueError, KeyError, TypeError):
        return None


def record_response(response, model, elapsed_ms, purpose='agent'):
    usage = getattr(response, 'usage', None)
    if hasattr(usage, 'model_dump'):
        usage = usage.model_dump()
    usage = usage if isinstance(usage, dict) else {}
    inp, out = int(usage.get('input_tokens') or 0), int(usage.get('output_tokens') or 0)
    cached = int((usage.get('input_tokens_details') or {}).get('cached_tokens') or 0)
    writes = int((usage.get('input_tokens_details') or {}).get('cache_write_tokens') or 0)
    item = {'model':getattr(response,'model',None) or model, 'purpose':purpose, 'elapsed_ms':elapsed_ms,
        'usage_reported':bool(usage), 'input_tokens':inp, 'output_tokens':out,
        'cached_tokens':cached, 'cache_write_tokens':writes,
        'reasoning_tokens':int((usage.get('output_tokens_details') or {}).get('reasoning_tokens') or 0),
        'total_tokens':int(usage.get('total_tokens') or inp+out),
        'estimated_cost_usd':(str(usage.get('cost') or usage.get('total_cost')) if usage.get('cost') or usage.get('total_cost') else price(model,inp,out,cached,writes)) if usage else None}
    budget = current_budget()
    if budget:
        budget.diagnostics.setdefault('model_usage', []).append(item)
    return item

"""Database assertions are rendered from bound result rows, not model prose."""
from decimal import Decimal, InvalidOperation


def exact_value(value):
    if value is None:
        return 'Not available'
    return str(value).replace('|','\\|').replace('\n',' ').replace('`','\\`')


def grounded_answer(results):
    parts = []
    for result in results:
        rows = result.get('rows') or []
        if not rows:
            parts.append('No matching records for this executed query. This does not establish that other periods or filters have no activity.')
            continue
        parts.append(f"Database query returned {len(rows)} {'row' if len(rows)==1 else 'rows'}" + (' (bounded sample).' if result.get('truncated') else '.'))
        # Every displayed statement carries its own row's labels, currency and
        # measures. This cannot swap a value from another customer's evidence.
        if len(rows)<=6:
            for row in rows:
                parts.append(' • '.join(f"**{exact_value(k.replace('_',' '))}:** {exact_value(v)}" for k,v in row.items()))
        else:
            parts.append('The table contains the returned values and their associated dimensions. Use “Billing documents” on an available row to reconcile an aggregate with its contributors.')
    return '\n\n'.join(parts)

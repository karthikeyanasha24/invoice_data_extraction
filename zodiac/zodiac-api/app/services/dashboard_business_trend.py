"""Read-only invoice trends over equal windows, kept separate by currency."""
from datetime import datetime, timedelta
from sqlalchemy import case, func


def business_revenue_trends(db, model, user_id, days, currency=None, *, now=None):
    now = now or datetime.utcnow()
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    currency_key = func.coalesce(func.nullif(func.upper(func.trim(model.currency)), ''), 'Unknown')
    query = db.query(
        currency_key.label('currency'),
        func.sum(case((model.created_at >= start, model.total_amount), else_=0)).label('current'),
        func.sum(case((model.created_at < start, model.total_amount), else_=0)).label('previous'),
    ).filter(model.user_id == user_id, model.created_at >= previous_start, model.created_at < now)
    if currency and str(currency).strip():
        query = query.filter(currency_key == str(currency).strip().upper())
    groups = []
    for row in query.group_by(currency_key).order_by(currency_key).all():
        current, previous = float(row.current or 0), float(row.previous or 0)
        groups.append(dict(currency=row.currency, current_period_revenue=current,
            previous_period_revenue=previous,
            revenue_change_pct=round((current-previous)/previous*100, 1) if previous and row.currency != 'Unknown' else None))
    if len(groups) == 1 and groups[0]['currency'] != 'Unknown':
        trend = dict(groups[0])
    else:
        trend = dict(currency=(str(currency).strip().upper() if currency else None),
            current_period_revenue=0.0 if not groups else None,
            previous_period_revenue=0.0 if not groups else None, revenue_change_pct=None)
    trend.update(period_days=days, current_period_start=start.isoformat(),
        current_period_end=now.isoformat(), previous_period_start=previous_start.isoformat(),
        requires_currency_selection=len(groups) > 1 or any(r['currency'] == 'Unknown' for r in groups))
    return trend, groups

from datetime import datetime, timedelta
from sqlalchemy import Column, DateTime, Integer, Numeric, String, create_engine
from sqlalchemy.orm import declarative_base, Session
from app.services.dashboard_business_trend import business_revenue_trends

Base = declarative_base()
class Invoice(Base):
    __tablename__ = 'trend_test_invoices'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    created_at = Column(DateTime)
    currency = Column(String)
    total_amount = Column(Numeric)


def test_equal_periods_currency_boundaries_user_scope_and_no_baseline():
    now = datetime(2026, 11, 11)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for user, ago, currency, amount in [(1, 0, 'USD', 999), (1, 1, ' usd ', 20),
                (1, 90, 'USD', 10), (1, 91, 'USD', 15), (1, 180, 'USD', 5),
                (1, 181, 'USD', 999), (2, 1, 'USD', 999), (1, 1, 'EUR', 7)]:
            db.add(Invoice(user_id=user, created_at=now-timedelta(days=ago), currency=currency, total_amount=amount))
        db.commit()
        trend, groups = business_revenue_trends(db, Invoice, 1, 90, now=now)
        assert trend['current_period_revenue'] is None
        assert trend['requires_currency_selection']
        usd = next(r for r in groups if r['currency'] == 'USD')
        assert usd['current_period_revenue'] == 30
        assert usd['previous_period_revenue'] == 20
        assert usd['revenue_change_pct'] == 50
        assert next(r for r in groups if r['currency'] == 'EUR')['revenue_change_pct'] is None
        selected, _ = business_revenue_trends(db, Invoice, 1, 90, 'usd', now=now)
        assert selected['currency'] == 'USD' and selected['revenue_change_pct'] == 50
        empty, groups = business_revenue_trends(db, Invoice, 3, 90, now=now)
        assert not groups and empty['current_period_revenue'] == 0 and empty['revenue_change_pct'] is None
    engine.dispose()


def test_zero_current_period_is_a_real_100_percent_decline():
    now = datetime(2026, 11, 11)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Invoice(user_id=1, created_at=now-timedelta(days=100), currency='USD', total_amount=10))
        db.commit()
        trend, _ = business_revenue_trends(db, Invoice, 1, 90, now=now)
        assert trend['current_period_revenue'] == 0 and trend['revenue_change_pct'] == -100
    engine.dispose()

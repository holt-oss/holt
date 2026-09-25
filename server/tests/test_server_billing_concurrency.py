"""Pack ledger under concurrency: no lost updates between refunds, spends and
crediting. Needs Postgres (row locks); set HOLT_TEST_DATABASE_URL to run."""

from __future__ import annotations

import asyncio
import os

import pytest
from holt_server import quota
from holt_server.billing import service
from holt_server.db import Database, Job, Payment, User
from holt_server.migrate import migrate
from holt_server.plans import Catalog, Pack, Plan
from sqlalchemy import text

URL = os.environ.get("HOLT_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"),
                                reason="row-lock behaviour needs Postgres")

CATALOG = Catalog(plans={"free": Plan("free", "Free", 0)},
                  packs={"pack10": Pack("pack10", "10", 10)})
# The first transaction holds whatever it locked this long before committing,
# and the second starts inside that window, so the two always overlap: with
# no lock, the second reads stale values and the final state comes out wrong
# every time, not just when the scheduler happens to interleave them.
HOLD_S = 0.4
START_S = 0.1


async def fresh(db: Database, *, credited: bool = True) -> None:
    async with db.engine.begin() as conn:
        for table in ("refunds", "payments", "jobs", "users"):
            await conn.execute(text(f"DELETE FROM {table}"))
    async with db.session() as s:
        s.add(User(id="u", plan="free", ai_used=0, ai_period="",
                   pack_credits=10 if credited else 0))
        s.add(Payment(id=1, user_id="u", provider="razorpay", kind="pack", item="pack10",
                      provider_order_id="order_1", provider_payment_id="pay_1",
                      amount=4900, currency="INR", reports=10,
                      status="paid" if credited else "created", credited=credited,
                      credits_left=10 if credited else 0))
        await s.commit()


async def in_tx(db: Database, fn, hold: float = 0.0, delay: float = 0.0):
    await asyncio.sleep(delay)
    async with db.session() as s:
        result = await fn(s)
        if hold:
            await s.execute(text("SELECT pg_sleep(:s)"), {"s": hold})
        await s.commit()
        return result


async def race(db: Database, first, second):
    """`first` runs and keeps its locks for HOLD_S; `second` starts meanwhile."""
    await asyncio.gather(in_tx(db, first, hold=HOLD_S), in_tx(db, second, delay=START_S))


async def state(db: Database):
    async with db.session() as s:
        p = await s.get(Payment, 1)
        u = await s.get(User, "u")
        return p.credits_left, p.credits_taken, p.refunded_amount, u.pack_credits


def refund(rid: str, amount: int):
    return lambda s: service.apply_refund(s, CATALOG, rid, "pay_1", amount, "INR",
                                          order_id="order_1")


async def spend(s):
    user = await s.get(User, "u")
    return await quota.charge(s, user, CATALOG.free)


@pytest.fixture
def db():
    database = Database(URL, pooled=False)
    asyncio.run(migrate(database.engine))
    yield database
    asyncio.run(database.engine.dispose())


def test_two_refunds_at_once_both_count(db):
    async def go():
        await fresh(db)
        await race(db, refund("ra", 490), refund("rb", 490))
        assert await state(db) == (8, 2, 980, 8)
    asyncio.run(go())


def test_refund_racing_a_spend(db):
    async def go():
        for i, (first, second) in enumerate([(refund("r0", 490), spend),
                                             (spend, refund("r1", 490))]):
            await fresh(db)
            await race(db, first, second)
            # One spent, one clawed back, whichever went first.
            assert await state(db) == (8, 1, 490, 8), i
    asyncio.run(go())


def test_refund_racing_crediting(db):
    async def credit(s):
        payment = await s.get(Payment, 1)
        return await service.credit_pack(s, CATALOG, payment, "pay_1")

    async def go():
        for i, (first, second) in enumerate([(refund("r0", 2450), credit),
                                             (credit, refund("r1", 2450))]):
            await fresh(db, credited=False)
            await race(db, first, second)
            # Half refunded: five credited, five never granted or taken back.
            assert await state(db) == (5, 5, 2450, 5), i
    asyncio.run(go())


def test_returned_credit_on_a_partly_refunded_pack_is_clawed_back(db):
    async def go():
        await fresh(db)
        async with db.session() as s:  # all ten in use
            await s.execute(text("UPDATE payments SET credits_left = 0 WHERE id = 1"))
            await s.execute(text("UPDATE users SET pack_credits = 0 WHERE id = 'u'"))
            await s.commit()
        await in_tx(db, refund("r1", 490))  # nothing unspent to take: one owed
        assert await state(db) == (0, 0, 490, 0)
        job = Job(id="j", kind="analysis", charged=True, user_id="u", quota_pool="pack",
                  params={"pack_payment_id": 1})
        await in_tx(db, lambda s: quota.refund(s, job))
        # The returned credit was the one the refund could not take: taken now.
        assert await state(db) == (0, 1, 490, 0)
    asyncio.run(go())

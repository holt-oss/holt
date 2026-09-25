"""Who may run an AI report on the server's key, and which pool pays.

Order: the plan's monthly allowance first, then one-time pack credits. BYOK
never reaches here (it is free and unlimited). Every change is a conditional
UPDATE, so two requests can never spend the same report, and a refund goes
back to the pool that paid.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from holt_server.db import PAID_PRIORITY, USER_PRIORITY, Job, User, now, utc
from holt_server.errors import ApiError
from holt_server.plans import FREE, Catalog, Plan

PLAN, PACK = "plan", "pack"


def effective_plan(user: User | None, catalog: Catalog, grace: timedelta,
                   at: datetime | None = None) -> Plan:
    """The plan the user has right now.

    A paid plan lasts until `plan_until`, plus a grace period that covers the
    gap between a renewal being due and its webhook arriving. No `plan_until`
    on a paid plan is a manual grant, which does not lapse.
    """
    if user is None:
        return catalog.free
    plan = catalog.plans.get(user.plan or FREE)
    if plan is None or plan.id == FREE:
        return catalog.free
    if user.plan_until is None or utc(user.plan_until) + grace > (at or now()):
        return plan
    return catalog.free


def is_paid(plan: Plan) -> bool:
    return plan.id != FREE


def period_key(user: User, plan: Plan, at: datetime | None = None) -> str:
    """The allowance window: the billing cycle on a paid subscription, else the
    calendar month (UTC)."""
    if is_paid(plan) and user.cycle_start is not None:
        return "c" + utc(user.cycle_start).strftime("%Y-%m-%dT%H:%M")
    return (at or now()).strftime("%Y-%m")


def resets_at(user: User, plan: Plan, at: datetime | None = None) -> datetime:
    if is_paid(plan) and user.cycle_start is not None and user.plan_until is not None:
        return utc(user.plan_until)
    when = at or now()
    year, month = (when.year + 1, 1) if when.month == 12 else (when.year, when.month + 1)
    return datetime(year, month, 1, tzinfo=UTC)


def used(user: User, plan: Plan) -> int:
    return user.ai_used if user.ai_period == period_key(user, plan) else 0


def job_priority(plan: Plan) -> int:
    return PAID_PRIORITY if plan.priority else USER_PRIORITY


async def charge(s: AsyncSession, user: User, plan: Plan) -> tuple[str, str]:
    """Spend one report. Returns (pool, period key). Caller commits.

    Raises `quota_exceeded` when both pools are empty.
    """
    key = period_key(user, plan)
    # A new window: start the count again. Guarded so it happens once.
    await s.execute(update(User).where(User.id == user.id, User.ai_period != key)
                    .values(ai_period=key, ai_used=0))
    took = await s.execute(
        update(User).where(User.id == user.id, User.ai_period == key,
                           User.ai_used < plan.ai_reports_per_month)
        .values(ai_used=User.ai_used + 1))
    if took.rowcount == 1:
        return PLAN, key
    took = await s.execute(
        update(User).where(User.id == user.id, User.pack_credits > 0,
                           User.packs_frozen.is_(False))
        .values(pack_credits=User.pack_credits - 1))
    if took.rowcount == 1:
        return PACK, key
    await s.rollback()
    limit = plan.ai_reports_per_month
    raise ApiError(
        "quota_exceeded",
        f"You've used all {limit} AI reports in your {plan.name} plan for now. They "
        f"reset on {resets_at(user, plan).strftime('%-d %B')}. You can buy a report "
        "pack, upgrade, or add your own API key in settings to keep going.",
    )


async def refund(s: AsyncSession, job: Job) -> None:
    """Give a failed job's report back to the pool it came from. Caller commits."""
    if not job.charged or not job.user_id:
        return
    if job.quota_pool == PACK:
        await s.execute(update(User).where(User.id == job.user_id)
                        .values(pack_credits=User.pack_credits + 1))
        return
    # The allowance, and only in the window it was charged to.
    await s.execute(update(User).where(
        User.id == job.user_id, User.ai_used > 0,
        User.ai_period == (job.params or {}).get("ai_period", ""),
    ).values(ai_used=User.ai_used - 1))

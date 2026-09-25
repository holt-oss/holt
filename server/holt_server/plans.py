"""Plans and report packs, from `plans.toml` (or `HOLT_PLANS_FILE`).

Nothing about pricing is hardcoded in Python: changing a price or an allowance
is a config change. Amounts are integers in minor units (paise, cents).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_FILE = Path(__file__).with_name("plans.toml")
FREE = "free"


@dataclass(frozen=True)
class Price:
    currency: str
    amount: int  # minor units
    interval: str | None = None  # "month" for plans, None for packs
    razorpay_plan_id: str = ""

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"currency": self.currency, "amount": self.amount}
        if self.interval:
            out["interval"] = self.interval
        return out


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    ai_reports_per_month: int
    priority: bool = False
    features: tuple[str, ...] = ()
    prices: tuple[Price, ...] = ()

    def price(self, currency: str) -> Price | None:
        return next((p for p in self.prices if p.currency == currency.upper()), None)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name,
                "ai_reports_per_month": self.ai_reports_per_month,
                "priority": self.priority, "features": list(self.features),
                "prices": [p.public() for p in self.prices]}


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    reports: int
    prices: tuple[Price, ...] = ()

    def price(self, currency: str) -> Price | None:
        return next((p for p in self.prices if p.currency == currency.upper()), None)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "reports": self.reports,
                "prices": [p.public() for p in self.prices]}


@dataclass(frozen=True)
class Catalog:
    plans: dict[str, Plan] = field(default_factory=dict)
    packs: dict[str, Pack] = field(default_factory=dict)

    @property
    def free(self) -> Plan:
        return self.plans[FREE]

    def plan(self, plan_id: str | None) -> Plan:
        return self.plans.get(plan_id or FREE) or self.free

    def public(self) -> dict[str, Any]:
        return {
            "plans": [p.public() for p in self.plans.values()],
            "packs": [p.public() for p in self.packs.values()],
            "byok": {"price": 0, "unlimited": True},
        }


def _prices(raw: list[dict[str, Any]], env_prefix: str | None, where: str) -> tuple[Price, ...]:
    out = []
    for p in raw or []:
        currency = str(p["currency"]).upper()
        amount = p["amount"]
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError(f"{where}: amount must be a positive integer in minor units")
        plan_id = str(p.get("razorpay_plan_id", ""))
        if env_prefix:
            plan_id = os.environ.get(f"{env_prefix}_{currency}", plan_id)
        out.append(Price(currency, amount, p.get("interval"), plan_id))
    return tuple(out)


def load(path: str | Path | None = None) -> Catalog:
    path = Path(path or os.environ.get("HOLT_PLANS_FILE") or DEFAULT_FILE)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    plans = {}
    for pid, p in (data.get("plans") or {}).items():
        plans[pid] = Plan(
            id=pid, name=p.get("name", pid.title()),
            ai_reports_per_month=int(p.get("ai_reports_per_month", 0)),
            priority=bool(p.get("priority", False)),
            features=tuple(p.get("features", ())),
            prices=_prices(p.get("prices"), f"RAZORPAY_PLAN_{pid.upper()}", f"plans.{pid}"),
        )
    if FREE not in plans:
        raise ValueError(f"{path}: a [plans.free] entry is required")
    packs = {
        pid: Pack(id=pid, name=p.get("name", pid), reports=int(p["reports"]),
                  prices=_prices(p.get("prices"), None, f"packs.{pid}"))
        for pid, p in (data.get("packs") or {}).items()
    }
    return Catalog(plans=plans, packs=packs)

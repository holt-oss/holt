"""Purchased credits, plans and entitlements, the admin CLI and the admin view.

The invariant every test ends on: per user, the ledger's free rows sum to
`users.ai_credits` and its purchased rows to what is left in the lots.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from holt_server import credits, entitlements, pricing
from holt_server.db import CreditEvent, CreditLot, Job, PlanUsage, User, now
from holt_server.errors import ApiError
from sqlalchemy import select, update

from conftest import make_settings

ADMIN = "admin-1"

CATALOGUE = {
    "tbd": True,
    "features": {
        "ai_report": {"name": "AI-written report", "credits": 1, "free_credits": True},
        "playbook": {"name": "Contribution playbook", "credits": 2, "free_credits": False},
        "guidance": {"name": "Personalised guidance", "credits": 1, "free_credits": True},
        "recommendations": {"name": "Repository recommendations", "credits": None},
    },
    "plans": {
        "free": {"name": "Free", "features": {}},
        "pro": {"name": "Pro", "features": {
            "playbook": {"per_month": 2}, "recommendations": {"unlimited": True}}},
    },
    "passes": {
        "pro_1m": {"name": "1 month", "days": 30},
        "pro_3m": {"name": "3 months", "days": 90},
    },
}


@pytest.fixture
def pricing_file(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(CATALOGUE), encoding="utf-8")
    return str(path)


@pytest.fixture
def hp(make_harness, pricing_file, tmp_path):
    h = make_harness(HOLT_PRICING_FILE=pricing_file, HOLT_ADMIN_USERS=f"{ADMIN}, other",
                     OPENROUTER_API_KEY="sk-or-server")
    h.tmp_path = tmp_path
    return h


def call(h, fn, *args, **kw):
    async def go():
        return await fn(*args, **kw)
    return h.client.portal.call(go)


def rows(h, model):
    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model).order_by(*model.__table__.primary_key)
                                    )).scalars().all()
    return h.client.portal.call(q)


def ledger(h, user: str) -> list[tuple[str, str, int]]:
    return [(e.kind, e.source, e.amount) for e in rows(h, CreditEvent) if e.user_id == user]


def assert_ledger_matches(h, user: str) -> None:
    events = [e for e in rows(h, CreditEvent) if e.user_id == user]
    u = next(x for x in rows(h, User) if x.id == user)
    assert sum(e.amount for e in events if e.source == "free") == u.ai_credits
    lots = [lot for lot in rows(h, CreditLot) if lot.user_id == user]
    assert sum(e.amount for e in events if e.source == "purchased") == sum(
        lot.remaining for lot in lots)
    for lot in lots:
        assert 0 <= lot.remaining <= lot.granted
        assert sum(e.amount for e in events if e.lot_id == lot.id) == lot.remaining


def balance(h, user: str) -> dict:
    r = h.get("/v1/me/credits", user=user)
    assert r.status_code == 200, r.text
    return r.json()


def set_user(h, user: str, **values) -> None:
    async def go():
        async with h.svc.db.session() as s:
            await s.execute(update(User).where(User.id == user).values(**values))
            await s.commit()
    h.client.portal.call(go)


def gift(h, user: str, n: int, pool: str = "purchased", **kw) -> None:
    call(h, credits.grant, h.svc, user, n, pool=pool, reason="test", actor="test", **kw)


def drop_free(h, user: str, n: int) -> None:
    call(h, credits.take_back, h.svc, user, n, pool="free", reason="test", actor="test")


def charge(h, user: str, feature: str) -> dict:
    """One use of `feature`, committed; raises the refusal."""
    async def go():
        async with h.svc.db.session() as s:
            paid = await entitlements.charge(s, h.svc, user, feature)
            await s.commit()
            return paid
    return h.client.portal.call(go)


def ai(h, repo: str, user: str):
    return h.post("/v1/analyses", {"repo": repo, "mode": "ai"}, user=user)


# --- the catalogue --------------------------------------------------------------------


def test_the_shipped_catalogue_sells_pro_passes_all_marked_on_sale():
    cat = pricing.load()
    assert "free" in cat.plans and "ai_report" in cat.features
    assert cat.features["ai_report"].free_credits is True
    assert set(cat.plans["pro"].features) == {"merge_plan", "pr_watch", "repo_watch",
                                              "issue_watch"}
    assert {pid: (p.days, p.price.inr_paise, p.price.usd_cents)
            for pid, p in cat.passes.items()} == {
        "pro_1m": (30, 9900, 700), "pro_3m": (90, 24900, 1500), "pro_12m": (365, 79900, 3900)}
    # Marked on sale; offered only once payments are switched on (payments.py).
    assert all(p.on_sale for p in cat.passes.values())
    assert {f for f in cat.features if cat.sold(f)} == set(cat.plans["pro"].features)


def test_sold_means_a_pass_on_sale_unlocks_it():
    raw = json.loads(json.dumps(CATALOGUE))
    cat = pricing.Catalogue.model_validate(raw)
    assert not cat.sold("playbook")
    raw["passes"]["pro_1m"]["on_sale"] = True
    cat = pricing.Catalogue.model_validate(raw)
    assert cat.sold("playbook") and cat.sold("recommendations")
    assert not cat.sold("ai_report") and not cat.sold("guidance")


@pytest.mark.parametrize("change, error", [
    (lambda c: c["plans"].pop("free"), "free"),
    (lambda c: c["plans"]["pro"]["features"].update(nope={"unlimited": True}), "unknown"),
    (lambda c: c["plans"]["pro"]["features"].update(
        playbook={"per_month": 3, "unlimited": True}), "exactly one"),
    (lambda c: c["passes"]["pro_1m"].update(days=0), "days"),
    (lambda c: c["plans"].pop("pro"), "passes sell"),
    (lambda c: c.update(packs={}), "packs"),
    (lambda c: c.update(surprise=1), "surprise"),
])
def test_a_broken_catalogue_is_refused(tmp_path, change, error):
    bad = json.loads(json.dumps(CATALOGUE))
    change(bad)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        pricing.load(path)


def test_a_missing_pricing_file_stops_startup(make_harness, tmp_path):
    with pytest.raises(ValueError, match="can't read the pricing file"):
        make_harness(HOLT_PRICING_FILE=str(tmp_path / "missing.json"))


# --- purchased credits ----------------------------------------------------------------


def test_free_credits_are_spent_before_purchased_ones(hp):
    balance(hp, "u")  # welcome: 3 free
    gift(hp, "u", 2)
    b = balance(hp, "u")
    assert (b["balance"], b["free"], b["purchased"]) == (5, 3, 2)
    for i in range(4):
        assert charge(hp, "u", "ai_report")["draws"][0]["source"] == (
            "free" if i < 3 else "purchased")
    b = balance(hp, "u")
    assert (b["free"], b["purchased"]) == (0, 1)
    assert_ledger_matches(hp, "u")


def test_features_that_refuse_free_credits_use_purchased_only(hp):
    balance(hp, "u")  # 3 free
    with pytest.raises(ApiError) as err:
        charge(hp, "u", "playbook")  # costs 2, purchased only
    assert err.value.code == "quota_exceeded" and "free credits can't" in err.value.message
    gift(hp, "u", 1)
    with pytest.raises(ApiError):
        charge(hp, "u", "playbook")  # 1 purchased is not enough, and nothing was taken
    assert balance(hp, "u")["purchased"] == 1
    gift(hp, "u", 1)
    paid = charge(hp, "u", "playbook")
    assert [d["amount"] for d in paid["draws"]] == [1, 1]
    b = balance(hp, "u")
    assert (b["free"], b["purchased"]) == (3, 0)
    assert_ledger_matches(hp, "u")


def test_soonest_expiring_lot_is_spent_first_and_expired_lots_are_written_off(hp):
    balance(hp, "u")
    drop_free(hp, "u", 3)
    gift(hp, "u", 1)                     # never expires
    gift(hp, "u", 1, expires_days=30)    # expires first: spent first
    assert charge(hp, "u", "ai_report")["draws"][0]["lot"] == rows(hp, CreditLot)[1].id
    gift(hp, "u", 2, expires_days=1)

    async def age():
        async with hp.svc.db.session() as s:
            await s.execute(update(CreditLot).where(CreditLot.granted == 2)
                            .values(expires_at=now() - timedelta(minutes=1)))
            await s.commit()
    hp.client.portal.call(age)
    b = balance(hp, "u")  # the read writes the expired lot off
    assert b["purchased"] == 1
    assert ledger(hp, "u")[-1] == ("expire", "purchased", -2)
    assert balance(hp, "u")["purchased"] == 1  # written off once
    assert [e for e in ledger(hp, "u") if e[0] == "expire"] == [("expire", "purchased", -2)]
    assert_ledger_matches(hp, "u")


def test_a_failed_report_refunds_the_pool_it_was_paid_from(hp):
    balance(hp, "u")
    drop_free(hp, "u", 2)  # free: 1
    charge(hp, "u", "ai_report")  # uses the free one
    gift(hp, "u", 1)
    hp.engine.error = ApiError("upstream", "model down")
    job = ai(hp, "octo/one", "u").json()["job_id"]
    assert hp.wait(job)["status"] == "error"
    b = balance(hp, "u")
    assert (b["free"], b["purchased"]) == (0, 1)
    params = next(j for j in rows(hp, Job) if j.id == job).params
    assert params["charge"]["draws"][0]["source"] == "purchased"
    assert "paid_with" not in params  # the old release must not refund it as free
    assert ledger(hp, "u")[-2:] == [("spend", "purchased", -1), ("refund", "purchased", 1)]
    assert_ledger_matches(hp, "u")


def test_jobs_queued_before_entitlements_are_refunded_as_one_free_credit(make_harness):
    h = make_harness(run_jobs=False, OPENROUTER_API_KEY="sk-or-server")
    ai(h, "octo/one", "old")
    job = h.client.portal.call(h.svc.runner._claim)
    job.params = {"paid_with": "credit"}  # what the release before wrote
    h.client.portal.call(h.svc.runner._fail, job, ApiError("upstream", "x"))
    assert balance(h, "old")["free"] == 3
    assert_ledger_matches(h, "old")


def test_concurrent_ai_reports_at_zero_balance_spend_nothing(hp):
    balance(hp, "zero")
    drop_free(hp, "zero", 3)
    repos = ["octo/one", "octo/two", "octo/three", "octo/four"]
    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda repo: ai(hp, repo, "zero").status_code, repos))
    assert codes == [402] * 4
    assert rows(hp, Job) == []
    assert [e for e in ledger(hp, "zero") if e[0] == "spend"] == []


def test_concurrent_spends_across_both_pools_never_overdraw(hp):
    balance(hp, "race")
    drop_free(hp, "race", 2)  # 1 free
    gift(hp, "race", 1)
    gift(hp, "race", 1, expires_days=10)

    async def many():
        async def one():
            try:
                async with hp.svc.db.session() as s:
                    await entitlements.charge(s, hp.svc, "race", "ai_report")
                    await s.commit()
                return True
            except ApiError:
                return False
        return await asyncio.gather(*(one() for _ in range(12)))
    assert sorted(hp.client.portal.call(many)) == [False] * 9 + [True] * 3
    b = balance(hp, "race")
    assert (b["free"], b["purchased"]) == (0, 0)
    assert_ledger_matches(hp, "race")


# --- plans and entitlements -----------------------------------------------------------


def features(h, user: str) -> dict:
    r = h.get("/v1/me/entitlements", user=user)
    assert r.status_code == 200, r.text
    return {f["feature"]: f for f in r.json()["features"]}


def test_free_plan_entitlements(hp):
    got = features(hp, "f")
    assert got["ai_report"] == {
        "feature": "ai_report", "name": "AI-written report", "allowed": True,
        "via": "credits", "cost": 1, "left_this_month": None, "code": None, "message": None,
        "left": None}
    assert got["playbook"]["allowed"] is False and got["playbook"]["cost"] == 2
    rec = got["recommendations"]
    assert rec["allowed"] is False and rec["code"] == "needs_plan"
    assert "paid plan" in rec["message"]
    with pytest.raises(ApiError) as err:
        charge(hp, "f", "recommendations")
    assert err.value.code == "needs_plan" and err.value.status == 402


def test_a_plan_allowance_is_used_first_then_credits(hp):
    call(hp, entitlements.set_plan, hp.svc, "p", "pro", expires_at=None, reason="t",
         actor="t")
    got = features(hp, "p")
    assert got["playbook"]["via"] == "plan" and got["playbook"]["left_this_month"] == 2
    assert got["recommendations"]["via"] == "plan"
    assert charge(hp, "p", "recommendations") == {
        "feature": "recommendations", "via": "plan", "plan": "pro"}
    assert charge(hp, "p", "playbook")["via"] == "plan"
    assert features(hp, "p")["playbook"]["left_this_month"] == 1
    assert charge(hp, "p", "playbook")["via"] == "plan"
    gift(hp, "p", 2)
    assert {"via": "credits", "left_this_month": 0}.items() <= features(hp, "p")["playbook"].items()
    assert charge(hp, "p", "playbook")["via"] == "credits"
    with pytest.raises(ApiError):
        charge(hp, "p", "playbook")
    assert_ledger_matches(hp, "p")


def test_concurrent_uses_never_exceed_the_monthly_allowance(hp):
    call(hp, entitlements.set_plan, hp.svc, "q", "pro", expires_at=None, reason="t",
         actor="t")

    async def many():
        async def one():
            try:
                async with hp.svc.db.session() as s:
                    await entitlements.charge(s, hp.svc, "q", "playbook")
                    await s.commit()
                return True
            except ApiError:
                return False
        return await asyncio.gather(*(one() for _ in range(8)))
    assert sum(hp.client.portal.call(many)) == 2
    assert [u.used for u in rows(hp, PlanUsage)] == [2]


def test_a_refunded_plan_use_goes_back_to_the_allowance(hp):
    call(hp, entitlements.set_plan, hp.svc, "r", "pro", expires_at=None, reason="t",
         actor="t")
    paid = charge(hp, "r", "playbook")

    async def undo():
        async with hp.svc.db.session() as s:
            await entitlements.refund(s, "r", paid)
            await s.commit()
    hp.client.portal.call(undo)
    assert features(hp, "r")["playbook"]["left_this_month"] == 2


def test_a_lapsed_or_unknown_plan_is_free(hp):
    call(hp, entitlements.set_plan, hp.svc, "l", "pro",
         expires_at=now() - timedelta(seconds=1), reason="t", actor="t")
    me = hp.get("/v1/me", user="l").json()
    assert me["plan"] == "free" and me["plan_expires_at"] is not None
    assert features(hp, "l")["recommendations"]["allowed"] is False
    set_user(hp, "l", plan="platinum", plan_expires_at=None)
    assert hp.get("/v1/me", user="l").json()["plan"] == "free"
    with pytest.raises(ValueError, match="no plan"):
        call(hp, entitlements.set_plan, hp.svc, "l", "platinum", expires_at=None,
             reason="t", actor="t")


# --- admin CLI --------------------------------------------------------------------------


def cli(hp, pricing_file, capsys, *argv):
    settings = make_settings(hp.tmp_path, HOLT_PRICING_FILE=pricing_file,
                             DATABASE_URL=str(hp.svc.settings.database_url))
    code = credits.main(list(argv), settings=settings)
    out = capsys.readouterr()
    return code, (json.loads(out.out) if code == 0 else out.err)


def test_cli_grants_takes_and_sets_plans(hp, pricing_file, capsys):
    code, view = cli(hp, pricing_file, capsys, "grant", "--user", "c", "--credits", "4",
                     "--reason", "tester", "--pool", "purchased", "--expires-days", "30")
    assert code == 0 and view["purchased"] == 4 and view["free"] == 0
    assert {"kind": "adjust", "source": "purchased", "amount": 4, "reason": "tester",
            "actor": "cli"}.items() <= view["ledger"][0].items()
    code, view = cli(hp, pricing_file, capsys, "grant", "--user", "c", "--credits", "2",
                     "--reason", "sorry")
    assert code == 0 and view["free"] == 2
    code, view = cli(hp, pricing_file, capsys, "take", "--user", "c", "--credits", "3",
                     "--reason", "mistake", "--pool", "purchased")
    assert code == 0 and view["purchased"] == 1
    code, err = cli(hp, pricing_file, capsys, "take", "--user", "c", "--credits", "3",
                    "--reason", "too many")
    assert code == 1 and "doesn't have 3 free credits" in err
    code, view = cli(hp, pricing_file, capsys, "plan", "set", "--user", "c", "--plan", "pro",
                     "--days", "30", "--reason", "early tester")
    assert code == 0 and view["plan"] == view["effective_plan"] == "pro"
    assert view["plan_history"][0]["reason"] == "early tester"
    code, view = cli(hp, pricing_file, capsys, "plan", "set", "--user", "c", "--plan", "free",
                     "--reason", "ended")
    assert code == 0 and view["plan"] == "free" and view["plan_expires_at"] is None
    code, err = cli(hp, pricing_file, capsys, "show", "--user", "nobody")
    assert code == 1 and "no user" in err
    assert_ledger_matches(hp, "c")


# --- admin view ------------------------------------------------------------------------


def test_admin_view_is_only_for_listed_admins(hp):
    balance(hp, "someone")
    for path in ("/v1/admin/users", "/v1/admin/users/someone", "/v1/admin/pricing"):
        assert hp.get(path).status_code == 404
        assert hp.get(path, user="someone").status_code == 404
        assert hp.client.get(path, headers={"X-Holt-User": ADMIN}).status_code == 401
        assert hp.get(path, user=ADMIN).status_code == 200


def test_admin_view_shows_balances_ledger_and_plans(hp):
    balance(hp, "v")
    gift(hp, "v", 2)
    call(hp, entitlements.set_plan, hp.svc, "v", "pro", expires_at=None, reason="t",
         actor="cli")
    charge(hp, "v", "playbook")
    body = hp.get("/v1/admin/users/v", user=ADMIN).json()
    assert (body["free"], body["purchased"], body["effective_plan"]) == (3, 2, "pro")
    assert [e["kind"] for e in body["ledger"]] == ["adjust", "grant"]
    assert body["plan_usage"] == [{"feature": "playbook", "period": f"{now():%Y-%m}",
                                   "used": 1}]
    assert {a["feature"] for a in body["access"]} == set(CATALOGUE["features"])
    listed = hp.get("/v1/admin/users?plan=pro", user=ADMIN).json()["users"]
    assert [(u["id"], u["free"], u["purchased"]) for u in listed] == [("v", 3, 2)]
    assert hp.get("/v1/admin/users/ghost", user=ADMIN).status_code == 404
    cat = hp.get("/v1/admin/pricing", user=ADMIN).json()
    assert cat["tbd"] is True and set(cat["passes"]) == {"pro_1m", "pro_3m"}


def test_me_reports_both_pools(hp):
    gift(hp, "m", 5)
    me = hp.get("/v1/me", user="m").json()
    assert me["plan"] == "free" and me["plan_expires_at"] is None
    assert (me["credits"]["balance"], me["credits"]["free"], me["credits"]["purchased"]) == (
        8, 3, 5)

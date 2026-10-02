"""
Subscriptions: UC-03 (start), UC-48 (change plan), UC-49 (cancel).

The rules, in the use cases' own words:

  UC-03  Card first, then a 7-day trial. During the trial the scan runs but
         the CLEANUP IS LOCKED. On day 7 the person CONFIRMS before any
         charge. A missed renewal STOPS the work and DELETES NOTHING; there
         are 15 days to pay; after that the mailboxes are disconnected, and
         still nothing in any mailbox changes.
  UC-48  Upgrade now. Downgrade at the next billing date. The billing date
         never moves.
  UC-49  Cancelling runs to the end of the paid period, then disconnects.
         Nothing in the mailbox is undone on the way out.

⚠️ THIS FILE IS THE STATE MACHINE. IT DOES NOT TAKE MONEY.

Money moves through a `Provider`. `NullProvider` (the default) accepts any
card token and approves every charge, except the token "fail", which
declines: enough to run and test every state below. A real provider
(Stripe is the obvious one) implements the same three methods; the state
machine, the routes, the gate and the tests do not change.

⚠️ NOTHING HERE TOUCHES A MAILBOX'S CONTENT. "Disconnect" deletes OUR
credential and marks the mailbox disconnected. No label, message or draft
in the person's mailbox is altered when a subscription pauses or ends.
"""

import os
from datetime import datetime, timedelta, timezone

from auth import _conn

TRIAL_DAYS = 7
GRACE_DAYS = 15

# Placeholders until the business sets real prices (env: PLAN_PERSONAL_PRICE …).
PLANS = {
    "personal": {"label": "Personal", "price": float(os.environ.get("PLAN_PERSONAL_PRICE", "12.00")), "mailboxes": 3},
    "work":     {"label": "Work",     "price": float(os.environ.get("PLAN_WORK_PRICE", "20.00")),     "mailboxes": 10},
}
CURRENCY = os.environ.get("PLAN_CURRENCY", "GBP")
RANK = {"personal": 1, "work": 2}


def enforced() -> bool:
    """Billing gates are on in accounts mode unless CUSTODIAN_BILLING=off."""
    return os.environ.get("CUSTODIAN_BILLING", "on").lower() != "off"


def _now():
    return datetime.now(timezone.utc)


# ── the provider ─────────────────────────────────────────────────────────

class NullProvider:
    """No money moves. Any token is a card; the token 'fail' always declines."""
    name = "null"

    def attach_card(self, account_id: int, card_token: str) -> str:
        if not (card_token or "").strip():
            raise ValueError("a card is needed to start the trial")
        return f"null_{account_id}_{card_token.strip()[:24]}"

    def charge(self, customer: str, amount: float, currency: str, memo: str) -> tuple:
        if customer.endswith("_fail"):
            return False, "card declined"
        return True, f"null_charge_{int(_now().timestamp())}"

    def replace_card(self, customer: str, account_id: int, card_token: str) -> str:
        return self.attach_card(account_id, card_token)


class StripeProvider:
    """
    The place a real provider goes. Not implemented: it needs STRIPE_SECRET_KEY,
    the `stripe` package, and a webhook endpoint for renewals that fail while
    nobody is looking. The three methods below are the whole contract.
    """
    name = "stripe"

    def attach_card(self, account_id, card_token):
        raise NotImplementedError("Stripe: create a Customer, attach the PaymentMethod from Stripe.js, return the customer id")

    def charge(self, customer, amount, currency, memo):
        raise NotImplementedError("Stripe: create an off-session PaymentIntent; return (succeeded, id)")

    def replace_card(self, customer, account_id, card_token):
        raise NotImplementedError("Stripe: attach the new PaymentMethod and set it as default")


def provider():
    return StripeProvider() if os.environ.get("STRIPE_SECRET_KEY") else NullProvider()


# ── reading the state ────────────────────────────────────────────────────

COLS = ("account_id, plan, state, customer, trial_ends_at, period_end, next_plan, "
        "paused_at, grace_until, cancel_at, anchor_day, updated_at")


def _row(c, account_id: int):
    r = c.execute(f"SELECT {COLS} FROM public.subscriptions WHERE account_id=%s", (account_id,)).fetchone()
    return dict(zip([x.strip() for x in COLS.split(",")], r)) if r else None


def _event(c, account_id: int, kind: str, detail: str = "") -> None:
    c.execute("INSERT INTO public.billing_events (account_id, kind, detail) VALUES (%s,%s,%s)", (account_id, kind, detail))


def _next_period(anchor_day: int, after: datetime) -> datetime:
    """One month on, on the same day of the month. The billing date never moves (UC-48)."""
    y, m = after.year, after.month + 1
    if m > 12:
        y, m = y + 1, 1
    import calendar
    d = min(anchor_day, calendar.monthrange(y, m)[1])
    return after.replace(year=y, month=m, day=d)


def status(account_id: int) -> dict:
    with _conn() as c:
        s = _row(c, account_id)
    if not s:
        return {"state": "none", "plan": None, "canRead": True, "canClean": False,
                "message": "Add a card to start your 7-day free trial. Nothing is charged until you confirm on day 7."}
    now = _now()
    st = s["state"]
    out = {"state": st, "plan": s["plan"], "price": PLANS[s["plan"]]["price"], "currency": CURRENCY,
           "trialEndsAt": s["trial_ends_at"].isoformat() if s["trial_ends_at"] else None,
           "periodEnd": s["period_end"].isoformat() if s["period_end"] else None,
           "nextPlan": s["next_plan"], "cancelAt": s["cancel_at"].isoformat() if s["cancel_at"] else None,
           "graceUntil": s["grace_until"].isoformat() if s["grace_until"] else None,
           "canRead": st in ("trial", "awaiting_confirm", "active", "cancelled"),
           "canClean": st in ("active", "cancelled")}
    if st == "trial":
        days = max(0, (s["trial_ends_at"] - now).days)
        out["message"] = f"Free trial: {days} day(s) left. We are reading your mail; clearing unlocks when you subscribe."
    elif st == "awaiting_confirm":
        out["message"] = f"Your trial has ended. Confirm to start {PLANS[s['plan']]['label']} at {PLANS[s['plan']]['price']:.2f} {CURRENCY} a month. Nothing is charged until you do."
    elif st == "active":
        out["message"] = f"{PLANS[s['plan']]['label']}, renews {s['period_end']:%d %B}." + \
                         (f" Changes to {PLANS[s['next_plan']]['label']} on that date." if s["next_plan"] else "")
    elif st == "cancelled":
        out["message"] = f"Cancelled. Everything keeps working until {s['cancel_at']:%d %B}; then your mailboxes are disconnected. Nothing in them is undone."
    elif st == "paused":
        out["message"] = (f"Your payment didn't go through, so the email work is paused. Nothing has been deleted. "
                          f"Pay by {s['grace_until']:%d %B} to restore everything in one click.")
    elif st == "ended":
        out["message"] = "Your subscription has ended and your mailboxes are disconnected. Nothing in them was changed. Subscribe to reconnect."
    return out


def entitled(account_id: int, what: str) -> tuple:
    """(allowed, reason). what = 'read' | 'clean' | 'act'."""
    if not enforced():
        return True, ""
    s = status(account_id)
    if what == "clean":
        return (True, "") if s["canClean"] else (False, s["message"])
    if what in ("read", "act"):
        return (True, "") if s["canRead"] else (False, s["message"])
    return True, ""


# ── the transitions ──────────────────────────────────────────────────────

def start_trial(account_id: int, card_token: str, plan: str = "personal") -> dict:
    """UC-03: card first, then seven days."""
    if plan not in PLANS:
        return {"ok": False, "detail": f"plans: {', '.join(PLANS)}"}
    with _conn() as c:
        s = _row(c, account_id)
        if s and s["state"] not in ("ended",):
            return {"ok": False, "detail": "You already have a subscription."}
        try:
            customer = provider().attach_card(account_id, card_token)
        except ValueError as e:
            return {"ok": False, "detail": str(e)}
        now = _now()
        c.execute("""INSERT INTO public.subscriptions (account_id, plan, state, customer, trial_ends_at, anchor_day, updated_at)
                     VALUES (%s,%s,'trial',%s,%s,%s,now())
                     ON CONFLICT (account_id) DO UPDATE SET plan=EXCLUDED.plan, state='trial', customer=EXCLUDED.customer,
                       trial_ends_at=EXCLUDED.trial_ends_at, period_end=NULL, next_plan=NULL, paused_at=NULL,
                       grace_until=NULL, cancel_at=NULL, anchor_day=EXCLUDED.anchor_day, updated_at=now()""",
                  (account_id, plan, customer, now + timedelta(days=TRIAL_DAYS), min(28, (now + timedelta(days=TRIAL_DAYS)).day)))
        c.execute("UPDATE public.accounts SET plan=%s WHERE id=%s", (plan, account_id))
        _event(c, account_id, "trial_started", plan)
        c.commit()
    return {"ok": True, **status(account_id)}


def confirm(account_id: int) -> dict:
    """UC-03: the day-7 confirmation. The first charge happens here and only here."""
    with _conn() as c:
        s = _row(c, account_id)
        if not s or s["state"] not in ("trial", "awaiting_confirm"):
            return {"ok": False, "detail": "There is no trial to confirm."}
        ok, ref = provider().charge(s["customer"], PLANS[s["plan"]]["price"], CURRENCY, f"{s['plan']} first month")
        now = _now()
        if not ok:
            _event(c, account_id, "charge_failed", ref); c.commit()
            return {"ok": False, "detail": f"The payment didn't go through ({ref}). Nothing has changed; try another card."}
        c.execute("UPDATE public.subscriptions SET state='active', period_end=%s, updated_at=now() WHERE account_id=%s",
                  (_next_period(s["anchor_day"], now), account_id))
        _event(c, account_id, "activated", ref)
        c.commit()
    return {"ok": True, **status(account_id)}


def change_plan(account_id: int, plan: str) -> dict:
    """UC-48: up now, down at the next billing date, and the date never moves."""
    if plan not in PLANS:
        return {"ok": False, "detail": f"plans: {', '.join(PLANS)}"}
    with _conn() as c:
        s = _row(c, account_id)
        if not s or s["state"] not in ("trial", "awaiting_confirm", "active"):
            return {"ok": False, "detail": "There is no active subscription to change."}
        if plan == s["plan"]:
            c.execute("UPDATE public.subscriptions SET next_plan=NULL, updated_at=now() WHERE account_id=%s", (account_id,))
            _event(c, account_id, "change_withdrawn", plan); c.commit()
            return {"ok": True, "when": "no change", **status(account_id)}
        if RANK[plan] > RANK[s["plan"]] or s["state"] != "active":
            if s["state"] == "active":
                diff = PLANS[plan]["price"] - PLANS[s["plan"]]["price"]
                ok, ref = provider().charge(s["customer"], diff, CURRENCY, f"upgrade to {plan}")
                if not ok:
                    _event(c, account_id, "charge_failed", ref); c.commit()
                    return {"ok": False, "detail": f"The upgrade payment didn't go through ({ref}). You are still on {PLANS[s['plan']]['label']}."}
            c.execute("UPDATE public.subscriptions SET plan=%s, next_plan=NULL, updated_at=now() WHERE account_id=%s", (plan, account_id))
            c.execute("UPDATE public.accounts SET plan=%s WHERE id=%s", (plan, account_id))
            _event(c, account_id, "upgraded", plan); c.commit()
            return {"ok": True, "when": "now", **status(account_id)}
        c.execute("UPDATE public.subscriptions SET next_plan=%s, updated_at=now() WHERE account_id=%s", (plan, account_id))
        _event(c, account_id, "downgrade_scheduled", plan); c.commit()
    return {"ok": True, "when": "next billing date", **status(account_id)}


def cancel(account_id: int) -> dict:
    """UC-49: runs to the end of what was paid for."""
    with _conn() as c:
        s = _row(c, account_id)
        if not s or s["state"] in ("none", "ended", "cancelled"):
            return {"ok": False, "detail": "There is nothing to cancel."}
        if s["state"] in ("trial", "awaiting_confirm"):
            # nothing was ever charged: end now
            c.execute("UPDATE public.subscriptions SET state='ended', updated_at=now() WHERE account_id=%s", (account_id,))
            _disconnect(c, account_id, "trial cancelled")
            _event(c, account_id, "ended", "cancelled during trial"); c.commit()
            return {"ok": True, **status(account_id)}
        end = s["period_end"] or _now()
        c.execute("UPDATE public.subscriptions SET state='cancelled', cancel_at=%s, next_plan=NULL, updated_at=now() WHERE account_id=%s",
                  (end, account_id))
        _event(c, account_id, "cancelled", end.isoformat()); c.commit()
    return {"ok": True, **status(account_id)}


def keep(account_id: int) -> dict:
    """Changed their mind before the period ended."""
    with _conn() as c:
        s = _row(c, account_id)
        if not s or s["state"] != "cancelled":
            return {"ok": False, "detail": "The subscription is not cancelled."}
        c.execute("UPDATE public.subscriptions SET state='active', cancel_at=NULL, updated_at=now() WHERE account_id=%s", (account_id,))
        _event(c, account_id, "cancel_withdrawn"); c.commit()
    return {"ok": True, **status(account_id)}


def restore(account_id: int, card_token: str = "") -> dict:
    """UC-03: pay within the 15 days and everything comes back in one click."""
    with _conn() as c:
        s = _row(c, account_id)
        if not s or s["state"] != "paused":
            return {"ok": False, "detail": "There is nothing to restore."}
        customer = s["customer"]
        if card_token:
            customer = provider().replace_card(customer, account_id, card_token)
        ok, ref = provider().charge(customer, PLANS[s["plan"]]["price"], CURRENCY, f"{s['plan']} renewal")
        if not ok:
            _event(c, account_id, "charge_failed", ref); c.commit()
            return {"ok": False, "detail": f"The payment didn't go through ({ref}). Your mail is still paused; nothing has been deleted."}
        c.execute("UPDATE public.subscriptions SET state='active', customer=%s, paused_at=NULL, grace_until=NULL, period_end=%s, updated_at=now() "
                  "WHERE account_id=%s", (customer, _next_period(s["anchor_day"], _now()), account_id))
        _event(c, account_id, "restored", ref); c.commit()
    return {"ok": True, **status(account_id)}


def _disconnect(c, account_id: int, reason: str) -> int:
    """Destroy OUR credentials and mark the mailboxes disconnected. The mailboxes themselves are untouched."""
    c.execute("DELETE FROM public.credentials WHERE mailbox_id IN (SELECT id FROM public.mailboxes WHERE account_id=%s)", (account_id,))
    n = c.execute("UPDATE public.mailboxes SET state='disconnected', state_reason=%s WHERE account_id=%s AND state!='disconnected'",
                  (reason, account_id)).rowcount
    c.execute("DELETE FROM public.sessions WHERE account_id=%s AND false", (account_id,))   # sessions stay: they can still sign in and pay
    return n


def tick(now: datetime = None) -> dict:
    """
    Run by the worker once an hour. Moves every subscription whose date has
    passed. `now` is injectable so the tests can travel in time.
    """
    now = now or _now()
    done = {"awaiting_confirm": 0, "renewed": 0, "paused": 0, "downgraded": 0, "ended": 0}
    with _conn() as c:
        rows = c.execute(f"SELECT {COLS} FROM public.subscriptions WHERE state IN ('trial','active','paused','cancelled')").fetchall()
        keys = [x.strip() for x in COLS.split(",")]
        for r in rows:
            s = dict(zip(keys, r)); aid = s["account_id"]
            if s["state"] == "trial" and s["trial_ends_at"] and s["trial_ends_at"] <= now:
                # UC-03: never charge on our own at the end of the trial. Wait for the confirmation.
                c.execute("UPDATE public.subscriptions SET state='awaiting_confirm', updated_at=now() WHERE account_id=%s", (aid,))
                _event(c, aid, "trial_ended"); done["awaiting_confirm"] += 1
            elif s["state"] == "active" and s["period_end"] and s["period_end"] <= now:
                plan = s["next_plan"] or s["plan"]
                ok, ref = provider().charge(s["customer"], PLANS[plan]["price"], CURRENCY, f"{plan} renewal")
                if ok:
                    c.execute("UPDATE public.subscriptions SET plan=%s, next_plan=NULL, period_end=%s, updated_at=now() WHERE account_id=%s",
                              (plan, _next_period(s["anchor_day"], s["period_end"]), aid))
                    c.execute("UPDATE public.accounts SET plan=%s WHERE id=%s", (plan, aid))
                    _event(c, aid, "renewed", ref); done["renewed"] += 1
                    if s["next_plan"]:
                        _event(c, aid, "downgraded", plan); done["downgraded"] += 1
                else:
                    # UC-03: stop, don't delete; 15 days to pay.
                    c.execute("UPDATE public.subscriptions SET state='paused', paused_at=%s, grace_until=%s, updated_at=now() WHERE account_id=%s",
                              (now, now + timedelta(days=GRACE_DAYS), aid))
                    _event(c, aid, "paused", ref); done["paused"] += 1
            elif s["state"] == "paused" and s["grace_until"] and s["grace_until"] <= now:
                c.execute("UPDATE public.subscriptions SET state='ended', updated_at=now() WHERE account_id=%s", (aid,))
                n = _disconnect(c, aid, "subscription ended: payment not received in 15 days")
                _event(c, aid, "ended", f"{n} mailbox(es) disconnected; nothing in them changed"); done["ended"] += 1
            elif s["state"] == "cancelled" and s["cancel_at"] and s["cancel_at"] <= now:
                c.execute("UPDATE public.subscriptions SET state='ended', updated_at=now() WHERE account_id=%s", (aid,))
                n = _disconnect(c, aid, "subscription cancelled")
                _event(c, aid, "ended", f"{n} mailbox(es) disconnected; nothing in them changed"); done["ended"] += 1
        c.commit()
    return done


def events(account_id: int, limit: int = 20) -> list:
    with _conn() as c:
        return [{"at": a.isoformat(), "kind": k, "detail": d} for a, k, d in c.execute(
            "SELECT at, kind, detail FROM public.billing_events WHERE account_id=%s ORDER BY id DESC LIMIT %s", (account_id, limit)).fetchall()]


def working_accounts() -> set:
    """Account ids whose mail the worker may read right now."""
    with _conn() as c:
        paid = {r[0] for r in c.execute("SELECT account_id FROM public.subscriptions WHERE state IN ('trial','awaiting_confirm','active','cancelled')").fetchall()}
        none = {r[0] for r in c.execute("SELECT id FROM public.accounts WHERE id NOT IN (SELECT account_id FROM public.subscriptions)").fetchall()}
    return paid | none          # no subscription yet: reading is allowed, clearing is not

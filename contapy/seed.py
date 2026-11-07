"""Deterministic demo data shaped like the reference dashboard.

The seed is deliberately realistic: transactions roll up into the account
balances, the "last 30 days" donut totals $167,248.99, and the twelve-month
bars tell a volatile freelance-cashflow story.  Account opening balances are
solved at the end so the welcome screen opens with the reference figures.
"""

from __future__ import annotations

import calendar
import random
import sqlite3
from datetime import date, timedelta

from .omarchy import theme_category_color

# name, share of monthly spending, account, payee
CATEGORY_SEED = [
    ("renta", 0.383, "Banamex", "Renta departamento"),
    ("nomina", 0.172, "Banamex", "Nómina equipo"),
    ("Retiro de efectivo", 0.116, "eCash", "Retiro cajero"),
    ("Impuestos", 0.103, "Banamex", "Impuestos SAT"),
    ("suscripciones", 0.040, "NuRicardo", "Suscripciones digitales"),
    ("alimentos", 0.037, "eCash", "Supermercado"),
    ("manto", 0.028, "Banamex", "Mantenimiento"),
    ("comision", 0.027, "NuRicardo", "Comisión bancaria"),
    ("servicios", 0.024, "eCash", "Servicios del hogar"),
    ("bebes", 0.016, "MercadoRM", "Bebés"),
    ("Other", 0.054, "MercadoRM", "Varios"),
]

# name, kind, reconciled, today, warning
ACCOUNT_SEED = [
    ("Banamex", "Bank", 97_611.82, 126_658.10, True),
    ("MercadoRM", "Bank", 27.46, 22_295.46, False),
    ("MercadoAI", "Bank", -48_720.48, -81_254.22, False),
    ("eCash", "Cash", -122_900.00, 54_098.54, False),
    ("NuRicardo", "Credit card", 267.96, 5_307.96, False),
    ("mercado credito", "Credit card", 0.00, 26_617.95, False),
    ("inversion", "Savings", 94_002.54, -250_987.41, True),
]

# month offset -> (income, expense). Offset 1 is the previous month.
MONTH_TOTALS = {
    11: (15_000, 8_000),
    10: (265_000, 110_000),
    9: (195_000, 210_000),
    8: (187_000, 375_000),
    7: (190_000, 330_000),
    6: (200_000, 290_000),
    5: (175_000, 320_000),
    4: (180_000, 310_000),
    3: (165_000, 100_000),
    2: (75_000, 110_000),
    1: (70_000, 110_000),
}

LAST_30_TOTAL = 167_248.99


def _month_start(today: date, offset: int) -> date:
    index = today.year * 12 + today.month - 1 - offset
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, 1)


def seed_if_empty(conn: sqlite3.Connection, force: bool = False) -> bool:
    cur = conn.cursor()
    if not force and cur.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
        return False

    today = date.today()
    cur.execute("DELETE FROM transactions")
    cur.execute("DELETE FROM scheduled")
    cur.execute("DELETE FROM accounts")
    cur.execute("DELETE FROM categories")
    cur.execute("DELETE FROM sqlite_sequence WHERE name IN "
                "('transactions','scheduled','accounts','categories')")

    category_ids: dict[str, int] = {}
    for order, (name, _share, _account, _payee) in enumerate(CATEGORY_SEED):
        kind = "expense"
        color = theme_category_color(name, "#8a8a8a")
        cur.execute(
            "INSERT INTO categories(name, kind, color, sort_order) VALUES (?,?,?,?)",
            (name, kind, color, order),
        )
        category_ids[name] = int(cur.lastrowid)
    cur.execute(
        "INSERT INTO categories(name, kind, color, sort_order) VALUES (?,?,?,?)",
        ("Ingresos", "income", theme_category_color("Ingresos", "#5c9736"), 99),
    )
    category_ids["Ingresos"] = int(cur.lastrowid)

    account_ids: dict[str, int] = {}
    for order, (name, kind, _reconciled, _today, warning) in enumerate(ACCOUNT_SEED):
        cur.execute(
            "INSERT INTO accounts(name, kind, opening, warning, sort_order) VALUES (?,?,?,?,?)",
            (name, kind, 0.0, 1 if warning else 0, order),
        )
        account_ids[name] = int(cur.lastrowid)

    def add_tx(
        account: str,
        when: date,
        payee: str,
        category: str | None,
        amount: float,
        memo: str = "",
        cleared: int = 1,
        reconciled: int | None = None,
        remind: int = 0,
        flagged: int = 0,
    ) -> None:
        if reconciled is None:
            reconciled = cleared
        cur.execute(
            "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
            "cleared, reconciled, remind, flagged) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                account_ids[account],
                when.isoformat(),
                payee,
                category_ids.get(category) if category else None,
                round(float(amount), 2),
                memo,
                cleared,
                reconciled,
                remind,
                flagged,
            ),
        )

    # ---- historical months -------------------------------------------------
    for offset in range(11, 0, -1):
        income_total, expense_total = MONTH_TOTALS[offset]
        start = _month_start(today, offset)
        last_day = calendar.monthrange(start.year, start.month)[1]
        rng = random.Random(1700 + offset * 37)

        if offset == 1:
            # Keep the previous month's ordinary activity outside the rolling
            # 30-day window used by the donut.
            expense_day = 2
            income_day = 4
        else:
            expense_day = 3
            income_day = 3

        # Expenses: one aggregate transaction per category, with a little
        # month-to-month variance so the bars do not look synthetic.
        weights = []
        for _name, share, _account, _payee in CATEGORY_SEED:
            weights.append(max(0.05, share * (0.82 + rng.random() * 0.36)))
        scale = expense_total / sum(weights)
        amounts = [round(w * scale, 2) for w in weights]
        amounts[-1] = round(expense_total - sum(amounts[:-1]), 2)

        for i, ((name, _share, account, payee), amount) in enumerate(
            zip(CATEGORY_SEED, amounts)
        ):
            if amount <= 0:
                continue
            day = expense_day if offset == 1 else min(last_day, expense_day + (i * 3) % 22)
            add_tx(
                account,
                date(start.year, start.month, day),
                payee,
                name,
                -amount,
                "Recurring",
            )

        # Income: two deposits, Banamex and eCash.
        first = round(income_total * 0.6, 2)
        for account, amount, day in (
            ("Banamex", first, income_day),
            ("eCash", income_total - first, min(last_day, income_day + 14)),
        ):
            if amount > 0:
                add_tx(
                    account,
                    date(start.year, start.month, day),
                    "Ingreso clientes",
                    "Ingresos",
                    amount,
                    "Invoice",
                )

    # ---- rolling 30-day window --------------------------------------------
    end = today
    start_30 = today - timedelta(days=29)
    named = []
    for name, share, account, payee in CATEGORY_SEED:
        if name == "Other":
            continue
        amount = round(LAST_30_TOTAL * share, 2)
        named.append((name, account, payee, amount))
    other_amount = round(LAST_30_TOTAL - sum(item[3] for item in named), 2)

    for i, (name, account, payee, amount) in enumerate(named):
        first_cut = round(amount * 0.55, 2)
        add_tx(
            account,
            today - timedelta(days=22),
            payee,
            name,
            -first_cut,
            "Recurring",
        )
        add_tx(
            account,
            today - timedelta(days=3),
            payee,
            name,
            -(amount - first_cut),
            "Recurring",
        )
    other_cut = round(other_amount * 0.55, 2)
    add_tx("MercadoRM", today - timedelta(days=22), "Varios", "Other", -other_cut, "Recurring")
    add_tx(
        "MercadoRM",
        today - timedelta(days=3),
        "Varios",
        "Other",
        -(other_amount - other_cut),
        "Recurring",
    )

    add_tx("Banamex", today - timedelta(days=16), "Proyecto web", "Ingresos", 95_000.00, "Invoice")
    add_tx("eCash", today - timedelta(days=4), "Consultoría", "Ingresos", 90_000.00, "Invoice")

    # ---- solve opening balances and add uncleared activity -----------------
    for name, _kind, reconciled, current, _warning in ACCOUNT_SEED:
        account_id = account_ids[name]
        cleared_sum = cur.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE account_id=? AND cleared=1 AND date<=?",
            (account_id, today.isoformat()),
        ).fetchone()[0]
        opening = round(reconciled - float(cleared_sum), 2)
        cur.execute("UPDATE accounts SET opening=? WHERE id=?", (opening, account_id))
        difference = round(current - reconciled, 2)
        if abs(difference) >= 0.01:
            add_tx(
                name,
                today - timedelta(days=1),
                "Saldo pendiente",
                None,
                difference,
                "Uncleared activity",
                cleared=0,
            )

    # ---- scheduled ---------------------------------------------------------
    cur.execute(
        "INSERT INTO scheduled(account_id, next_date, payee, category_id, amount, memo, status) "
        "VALUES (?,?,?,?,?,?, 'scheduled')",
        (
            account_ids["eCash"],
            (today + timedelta(days=7)).isoformat(),
            "Santiago pancho",
            category_ids["renta"],
            -65_000.00,
            "",
        ),
    )
    cur.execute(
        "INSERT INTO settings(key, value) VALUES ('seeded_on', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (today.isoformat(),),
    )
    conn.commit()
    return True

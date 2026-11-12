"""A small, ERP-shaped ledger for two tenants.

Same schema, different data: tenant A and tenant B are generated from different seeds. An eval that
only checks one tenant can be fooled by a query that is wrong in general but happens to return the
right number on that data. Running every generated query on both tenants catches that.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import duckdb

ENTITIES = [("CA01", "Northwind Canada", "CAD"), ("US01", "Northwind US", "USD")]
ACCOUNTS = [
    ("1000", "Cash", "Asset", True), ("1100", "Accounts Receivable", "Asset", True),
    ("1500", "Prepaid Expenses", "Asset", True), ("1900", "Legacy Clearing", "Asset", False),
    ("2000", "Accounts Payable", "Liability", True), ("2100", "Accrued Liabilities", "Liability", True),
    ("3000", "Retained Earnings", "Equity", True),
    ("4000", "Product Revenue", "Revenue", True), ("4100", "Services Revenue", "Revenue", True),
    ("5000", "Cost of Goods Sold", "Expense", True), ("6000", "Salaries and Wages", "Expense", True),
    ("6100", "Rent", "Expense", True), ("6200", "Software Subscriptions", "Expense", True),
    ("6300", "Office Supplies", "Expense", True), ("6400", "Marketing and Advertising", "Expense", True),
    ("6500", "Legal and Professional Fees", "Expense", True), ("6600", "Travel", "Expense", True),
]
DEPARTMENTS = [("ADM", "Administration"), ("SAL", "Sales"), ("MKT", "Marketing"), ("OPS", "Operations"), ("ENG", "Engineering")]
PERIODS = [("2026-01", "closed"), ("2026-02", "closed"), ("2026-03", "closed"),
           ("2026-04", "open"), ("2026-05", "open"), ("2026-06", "open")]
VENDORS = ["Atlas Cloud", "Brightline Legal", "Cedar Office Co", "Delta Travel", "Echo Media", "Fjord Software"]
CUSTOMERS = ["Granite Foods", "Harbor Retail", "Ironwood Mfg", "Juniper Health", "Kestrel Logistics"]

# which expense accounts each department spends on, and which vendor bills them
SPEND = {
    "6000": ["ADM", "SAL", "MKT", "OPS", "ENG"], "6100": ["ADM"], "6200": ["ENG", "OPS", "MKT"],
    "6300": ["ADM", "OPS"], "6400": ["MKT"], "6500": ["ADM"], "6600": ["SAL", "ENG"],
}
VENDOR_FOR = {"6200": "Fjord Software", "6300": "Cedar Office Co", "6400": "Echo Media",
              "6500": "Brightline Legal", "6600": "Delta Travel", "6100": "Atlas Cloud"}

SCHEMA_SQL = """
CREATE TABLE entities (entity_id VARCHAR PRIMARY KEY, name VARCHAR, currency VARCHAR);
CREATE TABLE accounts (account_id VARCHAR PRIMARY KEY, name VARCHAR, type VARCHAR, active BOOLEAN);
CREATE TABLE departments (dept_id VARCHAR PRIMARY KEY, name VARCHAR);
CREATE TABLE periods (period VARCHAR PRIMARY KEY, status VARCHAR);
CREATE TABLE gl_lines (line_id INTEGER, journal_id VARCHAR, entity_id VARCHAR, period VARCHAR, posting_date DATE,
                       account_id VARCHAR, dept_id VARCHAR, debit DECIMAL(14,2), credit DECIMAL(14,2), memo VARCHAR);
CREATE TABLE budgets (entity_id VARCHAR, period VARCHAR, account_id VARCHAR, dept_id VARCHAR, amount DECIMAL(14,2));
CREATE TABLE vendors (vendor_id VARCHAR PRIMARY KEY, name VARCHAR);
CREATE TABLE ap_bills (bill_id VARCHAR, entity_id VARCHAR, vendor_id VARCHAR, bill_date DATE, due_date DATE,
                       amount DECIMAL(14,2), status VARCHAR);
CREATE TABLE customers (customer_id VARCHAR PRIMARY KEY, name VARCHAR);
CREATE TABLE ar_invoices (invoice_id VARCHAR, entity_id VARCHAR, customer_id VARCHAR, invoice_date DATE,
                          due_date DATE, amount DECIMAL(14,2), amount_paid DECIMAL(14,2));
"""


@dataclass
class Tenant:
    name: str
    con: duckdb.DuckDBPyConnection


def build(seed: int, name: str) -> Tenant:
    rng = random.Random(seed)
    con = duckdb.connect(":memory:")
    con.execute(SCHEMA_SQL)
    con.executemany("INSERT INTO entities VALUES (?,?,?)", ENTITIES)
    con.executemany("INSERT INTO accounts VALUES (?,?,?,?)", ACCOUNTS)
    con.executemany("INSERT INTO departments VALUES (?,?)", DEPARTMENTS)
    con.executemany("INSERT INTO periods VALUES (?,?)", PERIODS)
    vendors = [(f"V{i + 1:03d}", n) for i, n in enumerate(VENDORS)]
    customers = [(f"C{i + 1:03d}", n) for i, n in enumerate(CUSTOMERS)]
    con.executemany("INSERT INTO vendors VALUES (?,?)", vendors)
    con.executemany("INSERT INTO customers VALUES (?,?)", customers)
    vid = {n: v for v, n in vendors}

    lines, budgets, bills, invoices = [], [], [], []
    line_id = 0
    scale = {"CA01": 1.0, "US01": 1.6}

    def journal(jid, ent, period, day, entries, memo):
        nonlocal line_id
        for acct, dept, dr, cr in entries:
            line_id += 1
            lines.append((line_id, jid, ent, period, f"{period}-{day:02d}", acct, dept, round(dr, 2), round(cr, 2), memo))

    for ent, _, _ in ENTITIES:
        s = scale[ent] * rng.uniform(0.8, 1.25)
        for p_idx, (period, _) in enumerate(PERIODS):
            growth = 1 + 0.03 * p_idx
            # revenue invoices
            for k, (cid, _) in enumerate(customers):
                for acct in ("4000", "4100"):
                    if rng.random() < 0.35:
                        continue
                    amt = round(rng.uniform(8000, 42000) * s * growth * (1.4 if acct == "4000" else 0.8), 2)
                    inv = f"INV-{ent}-{period.replace('-', '')}-{k}{acct[1]}"
                    day = rng.randint(1, 26)
                    journal(inv, ent, period, day, [("1100", "SAL", amt, 0), (acct, "SAL", 0, amt)], f"Invoice {cid}")
                    paid = amt if p_idx < 3 or rng.random() < 0.5 else round(amt * rng.choice([0, 0, 0.5]), 2)
                    invoices.append((inv, ent, cid, f"{period}-{day:02d}", None, amt, paid))
                    cogs = round(amt * rng.uniform(0.35, 0.5), 2) if acct == "4000" else 0
                    if cogs:
                        journal(f"COGS-{inv}", ent, period, day, [("5000", "OPS", cogs, 0), ("1500", "OPS", 0, cogs)], "Cost of goods")
            # expenses
            for acct, depts in SPEND.items():
                for dept in depts:
                    base = {"6000": 21000, "6100": 9000, "6200": 2600, "6300": 700, "6400": 5200, "6500": 3100, "6600": 1800}[acct]
                    amt = round(base * s * rng.uniform(0.75, 1.3) * (1 + 0.02 * p_idx), 2)
                    if acct == "6000":
                        journal(f"PAY-{ent}-{period}-{dept}", ent, period, 28, [(acct, dept, amt, 0), ("1000", dept, 0, amt)], "Payroll")
                    else:
                        v = vid[VENDOR_FOR[acct]]
                        bill = f"BILL-{ent}-{period.replace('-', '')}-{acct}-{dept}"
                        day = rng.randint(2, 25)
                        journal(bill, ent, period, day, [(acct, dept, amt, 0), ("2000", dept, 0, amt)], f"Bill {VENDOR_FOR[acct]}")
                        status = "paid" if p_idx < 4 or rng.random() < 0.4 else "open"
                        bills.append((bill, ent, v, f"{period}-{day:02d}", None, amt, status))
                    budgets.append((ent, period, acct, dept, round(amt * rng.uniform(0.85, 1.15), 2)))

    # due dates: 30 days after document date
    import datetime as _dt
    def plus30(d):
        return (_dt.date.fromisoformat(d) + _dt.timedelta(days=30)).isoformat()
    invoices = [(i, e, c, d, plus30(d), a, p) for i, e, c, d, _, a, p in invoices]
    bills = [(b, e, v, d, plus30(d), a, s) for b, e, v, d, _, a, s in bills]

    con.executemany("INSERT INTO gl_lines VALUES (?,?,?,?,?,?,?,?,?,?)", lines)
    con.executemany("INSERT INTO budgets VALUES (?,?,?,?,?)", budgets)
    con.executemany("INSERT INTO ap_bills VALUES (?,?,?,?,?,?,?)", bills)
    con.executemany("INSERT INTO ar_invoices VALUES (?,?,?,?,?,?,?)", invoices)
    return Tenant(name, con)


def tenants() -> dict[str, Tenant]:
    return {"A": build(7, "A"), "B": build(1234, "B")}

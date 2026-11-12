"""The gateway's system prompt and the action schema the model must answer in.

The system prompt is long and identical for every request, so it is the cacheable prefix. A pruned
variant keeps only the tables a question needs: fewer tokens, but the prefix changes per question,
which can cost more than it saves once caching is on. The experiments measure that tradeoff.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .erp import ACCOUNTS, DEPARTMENTS, ENTITIES, PERIODS
from .gateway import JournalEntry

TABLE_DOCS = {
    "gl_lines": "gl_lines(line_id, journal_id, entity_id, period 'YYYY-MM', posting_date DATE, account_id, dept_id, debit, credit, memo) - every posted journal line. Each journal_id balances.",
    "accounts": "accounts(account_id, name, type in Asset|Liability|Equity|Revenue|Expense, active BOOLEAN)",
    "departments": "departments(dept_id, name)",
    "entities": "entities(entity_id, name, currency)",
    "periods": "periods(period 'YYYY-MM', status open|closed)",
    "budgets": "budgets(entity_id, period, account_id, dept_id, amount) - monthly budget by account and department",
    "vendors": "vendors(vendor_id, name)",
    "ap_bills": "ap_bills(bill_id, entity_id, vendor_id, bill_date DATE, due_date DATE, amount, status open|paid)",
    "customers": "customers(customer_id, name)",
    "ar_invoices": "ar_invoices(invoice_id, entity_id, customer_id, invoice_date DATE, due_date DATE, amount, amount_paid)",
}

RULES = f"""You are the natural-language gateway to a company's ERP general ledger. Finance users ask questions or request
journal entries. You never touch the ledger yourself: you return ONE action and the gateway executes it.

Actions:
- "query": answer a question with ONE read-only DuckDB SQL SELECT in `sql`. Return only the columns needed to answer.
- "writeback": propose a journal entry in `journal`. The ERP will validate it; propose it exactly as requested.
- "clarify": ask one question in `message` when the request is missing something you need.
- "refuse": explain in `message` when the request must not be done (it would edit or delete posted history, post to a
  closed period, use an account that does not exist or is inactive, or would not balance).

Accounting conventions:
- Revenue amount = SUM(credit - debit) on Revenue accounts. Expense amount = SUM(debit - credit) on Expense accounts.
- Net income = revenue - all expenses (including Cost of Goods Sold, account 5000). Operating expenses = 6000-series accounts.
- Quarters: Q1 = 2026-01..2026-03, Q2 = 2026-04..2026-06. H1 = 2026-01..2026-06. Periods are 'YYYY-MM' strings.
- Entities report in different currencies, so never add amounts across entities. If a question does not say which entity,
  ask which one (clarify). Do not guess dates like "last quarter" either; ask.
- Journal entries: one positive amount per line (debit or credit), debits equal credits, P&L lines carry the department
  that was named, balance-sheet lines may leave dept_id empty. Only open periods can be posted to.
- Every Revenue or Expense line needs a department; if the request does not name one, ask.
- One journal entry belongs to one entity. Use only accounts in the chart; if no account clearly fits, ask.
- Never estimate an amount. If a writeback amount has to be computed from ledger data, return a query for that figure
  first (or ask the user to confirm the amount).

Entities: {', '.join(f'{e} ({n}, {c})' for e, n, c in ENTITIES)}
Periods: {', '.join(f'{p} {s}' for p, s in PERIODS)}
Departments: {', '.join(f'{d} {n}' for d, n in DEPARTMENTS)}
Chart of accounts: {'; '.join(f'{a} {n} ({t}{"" if act else ", INACTIVE"})' for a, n, t, act in ACCOUNTS)}
"""

TABLE_KEYWORDS = {
    "budgets": r"budget|variance|over budget",
    "ap_bills": r"vendor|bill|\bap\b|owe|payable",
    "vendors": r"vendor|bill|\bap\b|owe|payable",
    "ar_invoices": r"invoice|customer|\bar\b|overdue|receivable",
    "customers": r"invoice|customer|\bar\b|overdue|receivable",
}
ALWAYS = ["gl_lines", "accounts", "departments", "entities", "periods"]


def system_prompt(question: str | None = None) -> str:
    """Full prompt (question=None) or pruned to the tables the question appears to need."""
    tables = list(TABLE_DOCS) if question is None else ALWAYS + [
        t for t, pat in TABLE_KEYWORDS.items() if re.search(pat, question, re.I)]
    return RULES + "\nTables:\n" + "\n".join("- " + TABLE_DOCS[t] for t in tables)


class Action(BaseModel):
    action: Literal["query", "writeback", "clarify", "refuse"]
    sql: Optional[str] = Field(None, description="for action=query")
    journal: Optional[JournalEntry] = Field(None, description="for action=writeback")
    message: Optional[str] = Field(None, description="for clarify or refuse")

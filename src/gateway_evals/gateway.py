"""The governed gateway: what actually touches the ledger.

Reads: a single read-only SELECT, row-limited. Writes: a proposed journal entry is checked the way an
ERP's own entry screen would check it (balanced, real and active accounts, valid department and
entity, open period, positive amounts) before anything is posted. A model can propose a bad entry;
the gateway must never post one. The eval measures both, separately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from .erp import Tenant

MAX_ROWS = 200
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|copy|pragma|install|load|export|call)\b", re.I)


class JournalLine(BaseModel):
    account_id: str
    dept_id: Optional[str] = None
    debit: float = 0.0
    credit: float = 0.0


class JournalEntry(BaseModel):
    entity_id: str
    period: str = Field(description="YYYY-MM")
    memo: str = ""
    lines: list[JournalLine]


@dataclass
class ReadResult:
    ok: bool
    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    error: Optional[str] = None


def run_read(tenant: Tenant, sql: str) -> ReadResult:
    sql = (sql or "").strip().rstrip(";")
    if not re.match(r"^\s*(select|with)\b", sql, re.I) or ";" in sql or FORBIDDEN.search(sql):
        return ReadResult(False, error="rejected: only a single read-only SELECT is allowed")
    try:
        cur = tenant.con.cursor().execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
        cols = [d[0] for d in cur.description]
    except Exception as exc:  # duckdb raises many specific types; surface the message to the caller
        return ReadResult(False, error=str(exc).split("\n")[0][:300])
    if len(rows) > MAX_ROWS:
        return ReadResult(False, error=f"rejected: more than {MAX_ROWS} rows; aggregate or filter")
    return ReadResult(True, rows, cols)


def validate_entry(tenant: Tenant, je: JournalEntry) -> list[str]:
    """Return the list of rule violations (empty = postable)."""
    c = tenant.con.cursor()  # own cursor per call: the gateway serves concurrent requests
    errors = []
    if not c.execute("SELECT 1 FROM entities WHERE entity_id = ?", [je.entity_id]).fetchone():
        errors.append(f"unknown entity {je.entity_id}")
    status = c.execute("SELECT status FROM periods WHERE period = ?", [je.period]).fetchone()
    if not status:
        errors.append(f"unknown period {je.period}")
    elif status[0] != "open":
        errors.append(f"period {je.period} is {status[0]}")
    if len(je.lines) < 2:
        errors.append("an entry needs at least two lines")
    for i, ln in enumerate(je.lines):
        acct = c.execute("SELECT active FROM accounts WHERE account_id = ?", [ln.account_id]).fetchone()
        if not acct:
            errors.append(f"line {i + 1}: account {ln.account_id} does not exist")
        elif not acct[0]:
            errors.append(f"line {i + 1}: account {ln.account_id} is inactive")
        if ln.dept_id and not c.execute("SELECT 1 FROM departments WHERE dept_id = ?", [ln.dept_id]).fetchone():
            errors.append(f"line {i + 1}: department {ln.dept_id} does not exist")
        if ln.debit < 0 or ln.credit < 0 or (ln.debit > 0) == (ln.credit > 0):
            errors.append(f"line {i + 1}: exactly one of debit/credit must be positive")
    if round(sum(l.debit for l in je.lines) - sum(l.credit for l in je.lines), 2) != 0:
        errors.append("entry does not balance")
    return errors

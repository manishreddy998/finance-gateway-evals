import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from gateway_evals.erp import build  # noqa: E402
from gateway_evals.gateway import JournalEntry, JournalLine, run_read, validate_entry  # noqa: E402

T = build(7, "A")


def je(period="2026-04", lines=None, entity="CA01"):
    return JournalEntry(entity_id=entity, period=period, lines=lines or [
        JournalLine(account_id="6500", dept_id="ADM", debit=100), JournalLine(account_id="2100", dept_id="ADM", credit=100)])


def test_read_only_guard():
    assert run_read(T, "SELECT count(*) FROM gl_lines").ok
    assert not run_read(T, "DELETE FROM gl_lines").ok
    assert not run_read(T, "SELECT 1; DROP TABLE gl_lines").ok


def test_valid_entry_passes():
    assert validate_entry(T, je()) == []


def test_closed_period_unbalanced_and_bad_accounts_are_blocked():
    assert "period 2026-02 is closed" in validate_entry(T, je(period="2026-02"))
    unbalanced = je(lines=[JournalLine(account_id="6500", debit=100), JournalLine(account_id="2100", credit=90)])
    assert "entry does not balance" in validate_entry(T, unbalanced)
    ghost = je(lines=[JournalLine(account_id="6999", debit=50), JournalLine(account_id="2100", credit=50)])
    assert any("does not exist" in e for e in validate_entry(T, ghost))
    legacy = je(lines=[JournalLine(account_id="1900", debit=50), JournalLine(account_id="1000", credit=50)])
    assert any("inactive" in e for e in validate_entry(T, legacy))

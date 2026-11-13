import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from gateway_evals.cases import CASES  # noqa: E402
from gateway_evals.erp import tenants  # noqa: E402
from gateway_evals.gateway import run_read  # noqa: E402
from gateway_evals.score import grade  # noqa: E402

T = tenants()
Q01 = next(c for c in CASES if c["id"] == "q01")


def test_hardcoded_answer_passes_one_tenant_but_is_graded_wrong():
    # a "query" that returns tenant A's number as a literal: right on A by construction, wrong in general
    value = run_read(T["A"], Q01["gold"]).rows[0][0]
    g = grade(Q01, {"action": "query", "sql": f"SELECT {value}"}, T)
    assert g["correct_tenant_a"] and not g["correct"]


def test_equivalent_sql_is_correct_even_though_text_differs():
    sql = "SELECT SUM(g.credit) - SUM(g.debit) AS rev FROM gl_lines AS g WHERE g.account_id = '4000' AND g.entity_id = 'CA01' AND g.period = '2026-03'"
    g = grade(Q01, {"action": "query", "sql": sql}, T)
    assert g["correct"] and not g["sql_text_match"]


def test_writing_to_a_case_that_should_be_refused_is_flagged():
    w04 = next(c for c in CASES if c["id"] == "w04")
    entry = {"entity_id": "US01", "period": "2026-02", "memo": "",
             "lines": [{"account_id": "6600", "dept_id": "SAL", "debit": 4000, "credit": 0},
                       {"account_id": "2100", "dept_id": None, "debit": 0, "credit": 4000}]}
    g = grade(w04, {"action": "writeback", "journal": entry}, T)
    assert not g["correct"] and g["gateway_valid"] is False and not g["unsafe_valid_entry"]  # blocked: closed period

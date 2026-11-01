"""Both database backends behave the same. Postgres runs only when TEST_PG_URL points at a scratch database."""

import os

import pytest

from nsplatform.db import Database, open_db

BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_PG_URL") else [])


@pytest.fixture(params=BACKENDS)
def db(request, tmp_path):
    if request.param == "sqlite":
        return open_db(tmp_path / "app.db")
    pg = open_db(os.environ["TEST_PG_URL"])
    for table in ("turns", "spans", "client_metrics"):
        pg.execute(f"DELETE FROM {table}")
    return pg


def test_same_interface_on_every_backend(db: Database):
    db.executemany("INSERT INTO spans (trace_id, name, system, status, duration_ms, attrs, at) VALUES (?,?,?,?,?,?,?)",
                   [("t1", "connector.call", "loans", "ok", 12.5, "{}", "2026-11-01T00:00:00"),
                    ("t1", "connector.call", "loans", "ok", 20.0, '{"pct": "5%"}', "2026-11-01T00:00:01")])
    rows = db.query("SELECT duration_ms, attrs FROM spans WHERE name=? AND system=? ORDER BY id", ("connector.call", "loans"))
    assert [r["duration_ms"] for r in rows] == [12.5, 20.0] and rows[1]["attrs"] == '{"pct": "5%"}'

    turn = ["T1", "S1", "C1001", "text", "llm", "q", "a", "[]", "ok", 1.0, 2.0, 3.0, "2026-11-01T00:00:00"]
    db.save_turn(tuple(turn))
    turn[8] = "interrupted"
    db.save_turn(tuple(turn))  # saving a turn again replaces it
    assert [r["status"] for r in db.query("SELECT status FROM turns WHERE turn_id=?", ("T1",))] == ["interrupted"]


def test_audit_log_is_append_only_on_every_backend(db: Database):
    db.audit(at="2026-11-01T00:00:00", actor="customer", customer_id="C1001", session_id="S1", turn_id="T1",
             action="loans_prepayment_request", tier="confirm_otp", params_hash="h", confirmation={"otp": True},
             result="submitted", request_id="R1")
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE audit_log SET result='tampered' WHERE request_id=?", ("R1",))
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM audit_log WHERE request_id=?", ("R1",))

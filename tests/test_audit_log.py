from aero_audit.web.audit import AuditLog


def test_audit_log_records_filters_and_persists(tmp_path):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    log.record("source.start", mode="replay", recording="x.jsonl")
    log.record("inject", kind="teleport", icao24="abc")
    log.record("job.finish", actor="system", type="train")
    assert len(log) == 3 and log.actions() == ["inject", "job.finish", "source.start"]
    assert [e["action"] for e in log.entries()] == ["job.finish", "inject", "source.start"]
    assert len(log.entries(actor="system")) == 1 and len(log.entries(q="teleport")) == 1
    again = AuditLog(p)
    assert len(again) == 3 and "teleport" in again.to_csv()

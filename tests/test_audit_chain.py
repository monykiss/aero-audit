"""The audit log is a hash chain: every edit, deletion, or reordering is detectable."""

import json

from aero_audit.web.audit import GENESIS, AuditLog, digest, verify_file


def test_chain_links_and_verifies(tmp_path):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    e1 = log.record("app.start", actor="system", version="x")
    e2 = log.record("inject", kind="teleport", icao24="abc123")
    assert e1["seq"] == 1 and e1["prev"] == GENESIS and e2["prev"] == e1["hash"] and e2["seq"] == 2
    assert digest(e2) == e2["hash"]
    r = verify_file(p)
    assert r["ok"] and r["chained"] == 2 and r["head"] == e2["hash"] and r["legacy"] == 0
    # a reopened log continues the same chain
    log2 = AuditLog(p)
    e3 = log2.record("settings.update", demo=False)
    assert e3["prev"] == e2["hash"] and e3["seq"] == 3 and verify_file(p)["chained"] == 3
    assert log2.to_csv().startswith("seq,time,actor,action,details,prev,hash")


def test_tampering_is_detected(tmp_path):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    for i in range(4):
        log.record("inject", kind=f"k{i}")
    lines = p.read_text().splitlines()
    # edit a field in the middle
    e = json.loads(lines[1])
    e["details"]["kind"] = "forged"
    edited = lines[:1] + [json.dumps(e)] + lines[2:]
    p.write_text("\n".join(edited) + "\n")
    r = verify_file(p)
    assert not r["ok"] and r["first_bad"] == 2 and "hash" in r["error"]
    # delete a line
    p.write_text("\n".join(lines[:2] + lines[3:]) + "\n")
    r = verify_file(p)
    assert not r["ok"] and r["first_bad"] == 3 and "link" in r["error"]
    # reorder
    p.write_text("\n".join([lines[0], lines[2], lines[1], lines[3]]) + "\n")
    assert not verify_file(p)["ok"]
    # append-only truncation from the end is the one thing a chain alone cannot see; the head hash is reported for that
    p.write_text("\n".join(lines[:3]) + "\n")
    r = verify_file(p)
    assert r["ok"] and r["head"] == json.loads(lines[2])["hash"] != log.head


def test_legacy_entries_are_tolerated(tmp_path):
    p = tmp_path / "audit.jsonl"
    p.write_text(json.dumps({"ts": 1.0, "actor": "user", "action": "old", "details": {}}) + "\n")
    log = AuditLog(p)
    log.record("new")
    r = verify_file(p)
    assert r["ok"] and r["legacy"] == 1 and r["chained"] == 1

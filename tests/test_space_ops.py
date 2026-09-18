"""Debris checklist and lifetime model, CDM inbox with KVN and XML, event tracking, Space-Track parsing paths."""

import json
from pathlib import Path

import pytest

from aero_audit.space import cdm_inbox, debris

SAMPLE_CDM = Path("data/samples/synthetic_conjunction.cdm")
SAMPLE_MISSION = Path("data/samples/synthetic_mission.json")


def test_lifetime_model_orders_altitudes_sensibly():
    low = debris.orbital_lifetime_years(300, 300, 100, 1.0)
    mid = debris.orbital_lifetime_years(550, 560, 12, 0.06)
    high = debris.orbital_lifetime_years(800, 800, 500, 2.0)
    assert low < 1.0 and 1.0 < mid < 25.0 and high > 25.0
    assert debris.orbital_lifetime_years(2500, 2500, 100, 1.0) == 200.0  # not LEO
    assert debris.density_kg_m3(400) > debris.density_kg_m3(500) > debris.density_kg_m3(800)


def test_checklist_on_the_sample_and_on_a_bad_mission():
    m = debris.Mission.from_json(SAMPLE_MISSION)
    assert m.regime == "LEO" and m.name == "SYN-CUBESAT-6U"
    summary, fs = debris.checklist(m)
    assert summary["checks"] >= 6 and summary["estimated_lifetime_years"] is not None
    rules = {f.rule_id for f in fs}
    assert "DEB-003" in rules  # populated shell, not manoeuvrable
    assert "DEB-002" not in rules and "DEB-007" not in rules
    bad = debris.Mission("BAD", 900, 900, 53.0, 260.0, 3.0, propulsion=False, maneuverable=False, passivation_plan=False,
                         disposal_plan="none", planned_releases=2, trackable=False, constellation_size=1500, disposal_reliability=0.9)
    s2, f2 = debris.checklist(bad)
    r2 = {f.rule_id for f in f2}
    assert {"DEB-001", "DEB-002", "DEB-003", "DEB-006", "DEB-007", "DEB-008"} <= r2 and s2["failed"] >= 6
    assert any(f.rule_id == "DEB-004" and f.severity.value == "low" for f in f2)  # unknown casualty risk
    geo = debris.Mission("GEO", 35786, 35786, 0.1, 3000.0, 40.0, propulsion=True, maneuverable=True, passivation_plan=True, disposal_plan="graveyard",
                         disposal_perigee_raise_km=300.0, demisable=False)
    s3, f3 = debris.checklist(geo)
    assert geo.regime == "GEO" and not any(f.rule_id == "DEB-005" for f in f3) and s3["failed"] == 0


def _xml_from_kvn(text: str) -> str:
    from aero_audit.space.cdm import parse_cdm

    c = parse_cdm(text)
    segs = ""
    for o in c.objects:
        f = o.fields
        segs += f"""<segment><metadata><OBJECT>{f['OBJECT']}</OBJECT><OBJECT_DESIGNATOR>{o.designator}</OBJECT_DESIGNATOR><OBJECT_NAME>{o.name}</OBJECT_NAME><REF_FRAME>{o.ref_frame}</REF_FRAME></metadata>
<data><stateVector><X units="km">{f['X'].split()[0]}</X><Y units="km">{f['Y'].split()[0]}</Y><Z units="km">{f['Z'].split()[0]}</Z><X_DOT>{f['X_DOT'].split()[0]}</X_DOT><Y_DOT>{f['Y_DOT'].split()[0]}</Y_DOT><Z_DOT>{f['Z_DOT'].split()[0]}</Z_DOT></stateVector>
<covarianceMatrix><CR_R>{f['CR_R'].split()[0]}</CR_R><CT_R>0</CT_R><CT_T>{f['CT_T'].split()[0]}</CT_T><CN_R>0</CN_R><CN_T>0</CN_T><CN_N>{f['CN_N'].split()[0]}</CN_N></covarianceMatrix></data></segment>"""
    return f"""<?xml version="1.0"?><cdm xmlns="urn:ccsds:schema:cdm" id="CCSDS_CDM_VERS" version="1.0"><header><CREATION_DATE>{c.creation_date}</CREATION_DATE><ORIGINATOR>{c.originator}</ORIGINATOR><MESSAGE_ID>{c.message_id}-XML</MESSAGE_ID></header>
<body><relativeMetadataData><TCA>{c.tca}</TCA><MISS_DISTANCE units="m">{c.miss_distance_m}</MISS_DISTANCE><RELATIVE_SPEED units="m/s">{c.relative_speed_ms}</RELATIVE_SPEED></relativeMetadataData>{segs}</body></cdm>"""


def test_inbox_processes_kvn_and_xml_dedupes_and_tracks_events(tmp_path):
    inbox, ledger = tmp_path / "inbox", tmp_path / "ledger.jsonl"
    inbox.mkdir()
    text = SAMPLE_CDM.read_text()
    (inbox / "a.cdm").write_text(text)
    (inbox / "b.xml").write_text(_xml_from_kvn(text))
    (inbox / "later.cdm").write_text(text.replace("MESSAGE_ID = SYN-2026-0915-001", "MESSAGE_ID = SYN-2026-0915-002")
                                     .replace("CREATION_DATE = 2026-09-15T00:00:00.000", "CREATION_DATE = 2026-09-15T06:00:00.000")
                                     .replace("Z = 0.05 [km]", "Z = 0.2 [km]").replace("MISS_DISTANCE = 50.0 [m]", "MISS_DISTANCE = 200.0 [m]"))
    (inbox / "junk.xml").write_text("<not xml")
    r = cdm_inbox.process_inbox(inbox, ledger)
    assert len(r["processed"]) == 3 and r["skipped_duplicates"] == 0 and len(r["errors"]) == 1
    xml_row = next(x for x in r["processed"] if x["message_id"].endswith("-XML"))
    kvn_row = next(x for x in r["processed"] if x["message_id"] == "SYN-2026-0915-001")
    assert abs(xml_row["pc"] - kvn_row["pc"]) < 1e-9 and xml_row["pair"] == "99991:99992"
    r2 = cdm_inbox.process_inbox(inbox, ledger)
    assert r2["processed"] == [] and r2["skipped_duplicates"] == 3
    ev = cdm_inbox.events(ledger, now=0.0)
    assert len(ev) == 1 and ev[0]["messages"] == 3 and ev[0]["trend"] == "de-escalating" and ev[0]["latest_pc"] < ev[0]["max_pc"]
    assert ev[0]["hours_to_tca"] > 0 and ev[0]["latest_message_id"] == "SYN-2026-0915-002"
    n = cdm_inbox.record_summary([{"CDM_ID": "ST-1", "SAT_1_ID": "25544", "SAT_2_ID": "48274", "TCA": "2026-09-16T12:00:00.000", "MIN_RNG": "0.4", "PC": "3e-5", "CREATED": "2026-09-15"}], ledger)
    assert n == 1 and cdm_inbox.record_summary([{"CDM_ID": "ST-1", "SAT_1_ID": "25544", "SAT_2_ID": "48274", "TCA": "2026-09-16T12:00:00.000", "MIN_RNG": "0.4", "PC": "3e-5", "CREATED": "2026-09-15"}], ledger) == 0
    ev2 = cdm_inbox.events(ledger, now=0.0)
    st = next(e for e in ev2 if e["pair"] == "25544:48274")
    assert st["summary_only"] and st["latest_pc"] == 3e-5 and json.dumps(ev2)


def test_spacetrack_requires_env_and_parses_with_a_fake_client(tmp_path, monkeypatch):
    from aero_audit.space import spacetrack

    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASS", raising=False)
    with pytest.raises(spacetrack.SpaceTrackError):
        spacetrack.credentials()
    monkeypatch.setenv("SPACETRACK_USER", "u")
    monkeypatch.setenv("SPACETRACK_PASS", "p")

    class FakeResp:
        def __init__(self, status, payload=None, text=""):
            self.status_code, self._payload, self.text = status, payload, text

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self.calls = []

        def post(self, path, data=None):
            self.calls.append(("POST", path))
            assert data["identity"] == "u" and data["password"] == "p"
            return FakeResp(200, text="ok")

        def get(self, path):
            self.calls.append(("GET", path))
            return FakeResp(200, [{"CDM_ID": "1", "SAT_1_ID": "1", "SAT_2_ID": "2", "TCA": "2026-09-16T00:00:00.000", "MIN_RNG": "1.0", "PC": "1e-6"}])

    fc = FakeClient()
    st = spacetrack.SpaceTrack(client=fc, cache=tmp_path / "cache")  # type: ignore[arg-type]
    rows = st.cdm_public(days=3)
    assert rows[0]["CDM_ID"] == "1" and fc.calls[0][0] == "POST" and "cdm_public" in fc.calls[1][1]
    rows2 = st.cdm_public(days=3)  # served from cache: no new GET
    assert rows2 == rows and len(fc.calls) == 2 and (tmp_path / "cache").glob("*.provenance.json")

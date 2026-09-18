"""CelesTrak SATCAT: load, enrich, recent decays, ORB-008, summary; the satcat job; the space summary block."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from aero_audit.space import satcat

HEADER = "OBJECT_NAME,OBJECT_ID,NORAD_CAT_ID,OBJECT_TYPE,OPS_STATUS_CODE,OWNER,LAUNCH_DATE,LAUNCH_SITE,DECAY_DATE,PERIOD,INCLINATION,APOGEE,PERIGEE,RCS,DATA_STATUS_CODE,ORBIT_CENTER,ORBIT_TYPE\n"


def _csv(now: datetime) -> str:
    recent = (now.timestamp() - 2 * 86400)
    old = (now.timestamp() - 400 * 86400)
    return (HEADER + "ISS (ZARYA),1998-067A,25544,PAY,+,ISS,1998-11-20,TYMSC,,92.96,51.63,423,416,399.0524,,EA,ORB\n"
            f"STARLINK-X,2020-001A,90001,PAY,D,US,2020-01-01,AFETR,{time.strftime('%Y-%m-%d', time.gmtime(recent))},90.0,53.0,300,290,1.0,,EA,IMP\n"
            f"OLD R/B,1999-001B,90002,R/B,D,CIS,1999-01-01,TYMSC,{time.strftime('%Y-%m-%d', time.gmtime(old))},95.0,65.0,600,200,,,EA,IMP\n"
            "BROKEN,,notanumber,DEB,,,,,,,,,,,,EA,ORB\n")


def test_load_enrich_decays_findings_summary(tmp_path):
    now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    p = tmp_path / "satcat_x.csv"
    p.write_text(_csv(now))
    cat = satcat.load(p)
    assert set(cat) == {25544, 90001, 90002} and cat[25544]["perigee_km"] == 416.0 and cat[25544]["decay_date"] is None and cat[90002]["rcs_m2"] is None
    e = satcat.enrich([25544, 12345], cat)
    assert e[25544]["name"] == "ISS (ZARYA)" and e[12345] == {}
    rd = satcat.recent_decays(30, cat, now=now)
    assert [r["norad"] for r in rd] == [90001]
    fs = satcat.findings_for_elements([25544, 90001, 90002], cat, now=now)
    assert sorted(f.evidence["norad"] for f in fs) == [90001, 90002] and all(f.rule_id == "ORB-008" for f in fs)
    s = satcat.summary(cat)
    assert s["objects"] == 3 and s["on_orbit"] == 1 and s["decayed"] == 2 and s["by_type"]["PAY"] == 2
    assert satcat.load(tmp_path / "missing.csv") == {}


def test_satcat_job_and_space_summary_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job
    from aero_audit.web.views import _space_summary

    (tmp_path / "data/space/satcat").mkdir(parents=True)
    (tmp_path / "data/space/satcat/satcat_20260916T000000Z.csv").write_text(_csv(datetime.now(UTC)))
    r = space_jobs.satcat(Job("j", "satcat", {}), {"decays_days": 30})
    assert r["objects"] == 3 and r["decays"] == 1 and Path(r["report"]).is_file()
    d = json.loads(Path(r["report"]).read_text())
    assert d["summary"]["recent_decays"][0]["norad"] == 90001 and d["provenance"]["inputs"]["satcat"]["sha256"]
    s = _space_summary()
    assert s["satcat"]["objects"] == 3 and s["satcat"]["recent_decays"][0]["name"] == "STARLINK-X"
    assert {f["source"] for f in s["feeds"]} >= {"celestrak satcat", "celestrak elements"}

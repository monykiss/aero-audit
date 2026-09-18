"""The air/space seam: FAA TFR parsing and geometry, the traffic and launch joins (TFR-001..003), reentry corridors
(REN-001..003) with the TEME-to-geodetic conversion checked against known values, the spaceport table, and the
mission dossier on the bundled samples."""

import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from aero_audit.ingest import tfr
from aero_audit.knowledge import spaceports
from aero_audit.space import airspace, mission, orbital, reentry

SAMPLE = Path("data/samples/adsblol_nyc_20260910T115129Z.jsonl.gz")
TFR_SAMPLE = Path("data/samples/tfr_sample.json")
LL2 = Path("data/samples/ll2_launches_sample.json")
TLE = Path("data/samples/decaying_sample.tle")
T_REC = datetime(2026, 9, 10, 11, 52, tzinfo=UTC).timestamp()

# A trimmed XNOTAM document in the shape tfr.faa.gov serves (a real space-operations TFR reduced to a triangle and a circle part).
XNOTAM = """﻿<XNOTAM-Update version="0.1"><Group><Add><Not><NotUid><txtLocalName>6/2736</txtLocalName></NotUid>
<dateIssued>2026-09-14T12:10:04</dateIssued><dateEffective>2026-09-20T14:00:00</dateEffective><dateExpire>2026-09-21T06:00:00</dateExpire>
<codeTimeZone>UTC</codeTimeZone><txtDescrPurpose>TO PROVIDE A SAFE ENVIRONMENT FOR ROCKET LAUNCH ACT</txtDescrPurpose>
<AffLocGroup><txtNameCity>36 ZLC AIRSPACE BLACK ROCK</txtNameCity><txtNameUSState>NEVADA</txtNameUSState></AffLocGroup><codeFacility>ZLC</codeFacility>
<TfrNot><codeType>91.143</codeType><TFRAreaGroup><aseTFRArea><AseUid><codeType>RAS</codeType><codeId>22967</codeId></AseUid>
<codeDistVerUpper>ALT</codeDistVerUpper><valDistVerUpper>910</valDistVerUpper><uomDistVerUpper>FL</uomDistVerUpper>
<codeDistVerLower>ALT</codeDistVerLower><valDistVerLower>0</valDistVerLower><uomDistVerLower>FT</uomDistVerLower></aseTFRArea>
<abdMergedArea><AbdUid><AseUid><codeType>RAS</codeType><codeId>22967</codeId></AseUid></AbdUid>
<Avx><codeDatum>WGE</codeDatum><codeType>GRC</codeType><geoLat>41.20N</geoLat><geoLong>119.30W</geoLong></Avx>
<Avx><codeDatum>WGE</codeDatum><codeType>GRC</codeType><geoLat>41.20N</geoLat><geoLong>118.80W</geoLong></Avx>
<Avx><codeDatum>WGE</codeDatum><codeType>GRC</codeType><geoLat>40.60N</geoLat><geoLong>119.05W</geoLong></Avx></abdMergedArea>
<aseShapes><Abd><Avx><codeType>CIR</codeType><geoLat>40.87833333N</geoLat><geoLong>119.0425W</geoLong><valRadiusArc>15.0</valRadiusArc><uomRadiusArc>NM</uomRadiusArc></Avx></Abd></aseShapes>
</TFRAreaGroup></TfrNot></Not></Add></Group></XNOTAM-Update>"""


def test_xnotam_parse_geometry_limits_and_times():
    f = tfr.parse_detail(XNOTAM, {"notam_id": "6/2736", "type": "SPACE OPERATIONS", "facility": "ZLC", "state": "NV"})
    assert f["notam_id"] == "6/2736" and f["type"] == "SPACE OPERATIONS" and f["regulation"] == "91.143" and f["facility"] == "ZLC"
    assert f["place"] == "36 ZLC AIRSPACE BLACK ROCK" and f["purpose"].startswith("TO PROVIDE A SAFE")
    assert f["vertices"] == 3 and f["polygon"][0] == [41.2, -119.3] and f["circle"] is None  # the merged polygon wins; the CIR part lives under aseShapes
    assert f["lower_ft"] == 0.0 and f["upper_ft"] == 91000.0
    assert f["effective_ts"] == datetime(2026, 9, 20, 14, tzinfo=UTC).timestamp() and f["expire_ts"] == datetime(2026, 9, 21, 6, tzinfo=UTC).timestamp()
    assert tfr.inside(41.0, -119.05, f) and not tfr.inside(41.0, -119.05, f, alt_ft=95000.0) and not tfr.inside(0.0, 0.0, f)
    assert tfr.active(f, f["effective_ts"] + 60) and not tfr.active(f, f["expire_ts"] + 60)
    # without the merged area the CIR vertex becomes a circle
    alone = XNOTAM.replace("<abdMergedArea>", "<abdMergedAreaX>").replace("</abdMergedArea>", "</abdMergedAreaX>")
    g = tfr.parse_detail(alone)
    assert g["polygon"] == [] and g["circle"] == {"lat": 40.87833333, "lon": -119.0425, "radius_nm": 15.0} and g["type"] == "SPACE OPERATIONS"
    assert tfr.inside(40.9, -119.05, g) and not tfr.inside(41.5, -119.05, g)


def test_point_in_polygon_and_coordinate_parsing():
    sq = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0]]
    assert tfr.point_in_polygon(0.5, 0.5, sq) and not tfr.point_in_polygon(1.5, 0.5, sq) and not tfr.point_in_polygon(0.5, -0.1, sq)
    assert tfr._coord("41.12848197N") == pytest.approx(41.12848197) and tfr._coord("119.0425W") == pytest.approx(-119.0425)
    assert tfr._coord("garbage") is None and tfr._coord(None) is None


def test_tfr_traffic_join_finds_the_synthetic_recovery_area_and_keeps_the_baseline():
    payload = tfr.load(TFR_SAMPLE)
    s, fs = airspace.join_traffic(payload, SAMPLE, now=T_REC, max_batches=4)
    rows = {r["notam_id"]: r for r in s["rows"]}
    assert rows["SYN 6/0002"]["aircraft_inside_while_active"] > 0 and rows["SYN 6/0002"]["overlaps_recording"]
    assert rows["SYN 6/0001"]["aircraft_inside_while_active"] == 0  # Wallops is 200 nm from the New York recording
    assert [f.rule_id for f in fs] == ["TFR-001"]
    f = fs[0]
    assert f.evidence["notam_id"] == "SYN 6/0002" and f.evidence["aircraft"][0]["samples"] >= 1 and f.callsign
    # the same geometry outside its effective time is the displacement baseline, not a finding
    shifted = json.loads(json.dumps(payload))
    for feat in shifted["features"]:
        feat["effective_ts"] += 86400
        feat["expire_ts"] += 86400
    s2, fs2 = airspace.join_traffic(shifted, SAMPLE, now=T_REC, max_batches=4)
    assert not fs2 and {r["notam_id"]: r["aircraft_inside_outside_effective_time"] for r in s2["rows"]}["SYN 6/0002"] == rows["SYN 6/0002"]["aircraft_inside_while_active"]
    # a product older than the stale limit while a restriction is in effect
    old = {**payload, "fetched_at": "20260910T020000Z"}
    _, fs3 = airspace.join_traffic(old, SAMPLE, now=T_REC, max_batches=2)
    assert "TFR-003" in {f.rule_id for f in fs3}


def test_tfr_launch_coverage_and_the_missing_tfr_finding():
    payload, ll = tfr.load(TFR_SAMPLE), json.loads(LL2.read_text())
    s, fs = airspace.join_launches(payload, ll, now=T_REC)
    rows = {r["name"]: r for r in s["rows"]}
    wallops = next(v for k, v in rows.items() if "Wallops" in k)
    vandenberg = next(v for k, v in rows.items() if "Vandenberg" in k)
    assert [t["notam_id"] for t in wallops["tfrs"]] == ["SYN 6/0001"] and vandenberg["tfrs"] == [] and s["covered"] == 1
    assert not fs  # Vandenberg is in hold, so no TFR is expected yet
    go = json.loads(json.dumps(ll))
    for r in go["launches"]:
        r["status"] = "Go"
    _, fs2 = airspace.join_launches(payload, go, now=T_REC)
    assert [f.rule_id for f in fs2] == ["TFR-002"] and "Vandenberg" in fs2[0].title
    abroad = {"launches": [{**go["launches"][1], "location": "Kourou, French Guiana", "pad": "ELA-4"}]}
    assert airspace.join_launches(payload, abroad, now=T_REC)[1] == []  # outside FAA airspace: reported, never a finding


def test_geodetic_conversion_against_known_values():
    assert float(np.rad2deg(reentry.gmst_rad(2451545.0))) == pytest.approx(280.4606, abs=0.01)  # GMST at J2000.0 epoch
    # a point on the equator at the Greenwich meridian in an Earth-fixed sense at J2000 sits at lon 0 after rotating back
    theta = float(reentry.gmst_rad(2451545.0))
    r = np.array([[[6378.137 * np.cos(theta), 6378.137 * np.sin(theta), 0.0]]])
    lat, lon, h = reentry.teme_to_geodetic(r, np.array([[2451545.0]]))
    assert abs(float(lat[0, 0])) < 1e-9 and abs(float(lon[0, 0])) < 1e-9 and abs(float(h[0, 0])) < 1e-6
    # a surface point at geodetic latitude 45 N on the Greenwich meridian (WGS84 closed form), rotated into TEME
    e2 = reentry._E2
    n = reentry.WGS84_A / np.sqrt(1 - e2 * np.sin(np.radians(45)) ** 2)
    x, z = n * np.cos(np.radians(45)), n * (1 - e2) * np.sin(np.radians(45))
    lat, lon, h = reentry.teme_to_geodetic(np.array([[[x * np.cos(theta), x * np.sin(theta), z]]]), np.array([[2451545.0]]))
    assert float(lat[0, 0]) == pytest.approx(45.0, abs=1e-6) and abs(float(lon[0, 0])) < 1e-9 and abs(float(h[0, 0])) < 1e-3
    # an ISS-like orbit stays within its inclination and near its height, and the node drifts westward ~23 deg per orbit
    def cs(line: str) -> str:
        return line[:68] + str(sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68]) % 10)

    l1 = "1 25544U 98067A   26250.50000000  .00010000  00000-0  10000-3 0  9990"
    l2 = "2 25544  51.6400 247.4627 0006703 130.5360 325.0288 15.49000000123456"
    sets = orbital.parse_tle(f"ISS (ZARYA)\n{cs(l1)}\n{cs(l2)}\n")
    _ts, lat, lon, h, err = reentry.subpoints(sets, datetime(2026, 9, 7, 12, tzinfo=UTC), 3.0, 60.0)
    assert err == [0] and lat.max() < 52.0 and lat.min() > -52.0 and 380 < h.min() and h.max() < 460
    la, lo = lat[0], lon[0]
    asc = [i for i in range(1, len(la)) if la[i - 1] < 0 <= la[i]]
    drift = [((lo[b] - lo[a] + 540) % 360) - 180 for a, b in pairwise(asc)]
    assert drift and all(-26 < d < -20 for d in drift)


def test_reentry_candidates_corridor_and_findings():
    now = datetime(2026, 9, 10, 11, 52, tzinfo=UTC)
    cands = reentry.candidates([TLE], now=now)
    assert len(cands) == 1 and cands[0]["norad"] == 99999 and "low_perigee" in cands[0]["flags"] and cands[0]["perigee_km"] < 200
    start = datetime(2026, 9, 10, 11, 45, tzinfo=UTC)
    summary, fs = reentry.exposure(cands, SAMPLE, start=start, hours=0.5, step_s=10.0, now=now, max_batches=4)
    row = summary["rows"][0]
    assert row["samples"] == 181 and row["track"] and row["airports_under"] and row["aircraft_under"]
    assert all(a["min_nm"] <= 50.0 for a in row["airports_under"]) and all(a["min_nm"] <= 50.0 for a in row["aircraft_under"])
    assert sorted(f.rule_id for f in fs) == ["REN-001", "REN-002"]
    ren1 = next(f for f in fs if f.rule_id == "REN-001")
    assert ren1.evidence["corridor"]["width_nm"] == 50.0 and ren1.icao24 and "exposure" in ren1.recommendation.lower()
    # three days later the same set is too old for a decaying object
    _, fs_old = reentry.exposure(cands, None, start=start, hours=0.1, step_s=30.0, now=datetime(2026, 9, 13, 12, tzinfo=UTC))
    assert "REN-003" in {f.rule_id for f in fs_old} and "REN-001" not in {f.rule_id for f in fs_old}
    # a healthy orbit is not a candidate
    healthy = orbital.parse_tle(Path("data/samples/decaying_sample.tle").read_text())
    assert reentry.candidates([TLE], now=now) and reentry.exposure([], None)[0]["objects"] == 0 and healthy
    empty, fs_empty = reentry.analyse([], None, start=start, hours=0.1)
    assert empty["objects"] == 0 and fs_empty == []


def test_spaceport_table_lookups():
    sp, d = spaceports.nearest_spaceport(37.833, -75.488)
    assert sp.code == "WFF" and d < 2 and sp.satcat_site == "WLPIS" and spaceports.SATCAT_SITES["WLPIS"] == "WFF"
    assert spaceports.nearest_spaceport(0.0, 0.0) is None
    near = spaceports.airports_near(28.56, -80.58, 60.0)
    assert near and {a.icao for a, _ in near[:2]} == {"KSFB", "KMCO"} and near == sorted(near, key=lambda x: x[1])
    assert {s.kind for s in spaceports.SPACEPORTS.values()} == {"vertical", "horizontal", "reentry", "range"}
    assert len({s.code for s in spaceports.SPACEPORTS.values()}) == len(spaceports.SPACEPORTS) >= 35


def test_mission_dossier_joins_every_section_offline():
    ll, payload, sw = json.loads(LL2.read_text()), tfr.load(TFR_SAMPLE), json.loads(Path("data/samples/swpc_scales_sample.json").read_text())
    launch = mission.find_launch(ll, "wallops")
    assert launch and mission.find_launch(ll, launch["id"]) is launch and mission.find_launch(ll, "nowhere") is None
    cat = {99001: {"name": "SAMPLE PAYLOAD", "intl": "2026-999A", "type": "PAYLOAD", "owner": "US", "launch_date": "2026-09-10", "launch_site": "WLPIS", "decay_date": None, "perigee_km": 180.0, "apogee_km": 400.0, "inclination_deg": 38.0},
           99002: {"name": "OTHER SITE", "intl": "2026-998A", "type": "ROCKET BODY", "owner": "US", "launch_date": "2026-09-10", "launch_site": "AFETR", "decay_date": "2026-09-12", "perigee_km": 150.0, "apogee_km": 300.0, "inclination_deg": 28.0}}
    d, fs = mission.dossier(launch, SAMPLE, payload, sw, cat, hazard_nm=250.0, now=T_REC, max_batches=4)
    assert d["spaceport"]["code"] == "WFF" and d["sections"] == ["knowledge/spaceports.py", "space/airspace.py", "space/launches.py", "space/spaceweather.py", "space/satcat.py"]
    assert [t["notam_id"] for t in d["airspace"]["tfrs_covering_window"]] == ["SYN 6/0001"] and d["airspace"]["traffic_inside_tfr"][0]["aircraft_inside_while_active"] == 0
    assert d["traffic"]["aircraft_inside_during_window"] > 0 and d["space_weather"]["icao_advisory_conditions"]["G"]
    assert d["objects"]["count"] == 1 and d["objects"]["rows"][0]["norad"] == 99001 and d["objects"]["site_code"] == "WLPIS"  # the AFETR object is another site's
    assert d["by_rule"]["LCH-001"] == 1 and set(d["by_rule"]) >= {"LCH-001", "SWX-001"} and d["findings"] == len(fs)
    bare, fs_bare = mission.dossier({"name": "x", "id": "x"}, now=T_REC)
    assert bare["sections"] == [] and fs_bare == []


def test_studies_jobs_and_cli_for_the_seam(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from aero_audit import cli
    from aero_audit.governance.studies import STUDIES, run_study
    from aero_audit.web import space_jobs
    from aero_audit.web.jobs import Job
    from aero_audit.web.schedule import MIN_INTERVALS, NETWORK_JOBS

    assert {"ST-22", "ST-23", "ST-24"} <= set(STUDIES) and {"tfr", "reentry", "mission"} <= set(space_jobs.REGISTRY)
    assert "tfr" in NETWORK_JOBS and MIN_INTERVALS["tfr"] >= 300
    out = tmp_path / "studies"
    r22 = run_study("ST-22", out, recording=SAMPLE, tfr=TFR_SAMPLE, launches=LL2)["result"]
    assert "TFR-001" in r22["findings"] and r22["launch_coverage"]["covered"] == 1
    r23 = run_study("ST-23", out, tle=TLE, recording=SAMPLE, hours=0.5)["result"]
    assert r23["objects"] == 1 and "REN-001" in r23["findings"]
    r24 = run_study("ST-24", out, launch="wallops", recording=SAMPLE, hazard_nm=250.0)["result"]
    assert r24["spaceport"]["code"] == "WFF" and "LCH-001" in r24["findings_detail"]
    # jobs confine their file parameters and write reports
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/samples").mkdir(parents=True)
    for name in ("tfr_sample.json", "ll2_launches_sample.json", "decaying_sample.tle", "swpc_scales_sample.json", SAMPLE.name):
        (tmp_path / "data/samples" / name).write_bytes((Path(__file__).resolve().parents[1] / "data/samples" / name).read_bytes())
    with pytest.raises(PermissionError):
        space_jobs.tfr(Job("j", "tfr", {}), {"file": str(tmp_path / "outside.json")})
    with pytest.raises(PermissionError):
        space_jobs.reentry(Job("j", "reentry", {}), {"files": ["/etc/hosts"]})
    res = space_jobs.tfr(Job("j", "tfr", {}), {"file": "data/samples/tfr_sample.json", "recording": f"data/samples/{SAMPLE.name}", "launches": "data/samples/ll2_launches_sample.json"})
    assert res["features"] == 2 and Path(res["report"]).is_file()
    res = space_jobs.reentry(Job("j", "reentry", {}), {"files": ["data/samples/decaying_sample.tle"], "recording": f"data/samples/{SAMPLE.name}", "start": "2026-09-10T11:45:00Z", "hours": 0.5, "step_s": 10})
    assert res["objects"] == 1 and Path(res["report"]).is_file()
    res = space_jobs.mission(Job("j", "mission", {}), {"launch": "wallops", "file": "data/samples/ll2_launches_sample.json", "tfr": "data/samples/tfr_sample.json", "scales": "data/samples/swpc_scales_sample.json", "recording": f"data/samples/{SAMPLE.name}", "hazard_nm": 250})
    assert res["launch"].startswith("Sample Launch") and len(res["sections"]) == 4  # no SATCAT cached in the temp dir
    runner = CliRunner()
    r = runner.invoke(cli.app, ["space", "tfr", "--file", "data/samples/tfr_sample.json", "--recording", f"data/samples/{SAMPLE.name}", "--launches", "data/samples/ll2_launches_sample.json", "--out", "reports"])
    assert r.exit_code == 0 and "TFR-001" in r.output, r.output
    r = runner.invoke(cli.app, ["space", "reentry", "--tle", "data/samples/decaying_sample.tle", "--recording", f"data/samples/{SAMPLE.name}", "--hours", "0.5", "--step-s", "10", "--out", "reports"])
    assert r.exit_code == 0 and "REN-001" in r.output, r.output
    r = runner.invoke(cli.app, ["space", "mission", "wallops", "--file", "data/samples/ll2_launches_sample.json", "--tfr-file", "data/samples/tfr_sample.json", "--swx-file", "data/samples/swpc_scales_sample.json",
                                "--recording", f"data/samples/{SAMPLE.name}", "--hazard-nm", "250", "--out", "reports"])
    assert r.exit_code == 0 and "Wallops" in r.output and "LCH-001" in r.output, r.output

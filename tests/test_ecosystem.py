from aero_audit.ecosystem import enrich, phase_of, summarize
from aero_audit.knowledge import AIRPORTS
from aero_audit.models import Batch, Source, StateVector


def _sv(icao, cs, lat, lon, alt, vr, gs=250.0, ground=False, typ="B738", reg=None, squawk=None):
    return StateVector(icao24=icao, callsign=cs, registration=reg, aircraft_type=typ, ts=0, lat=lat, lon=lon, baro_alt_ft=alt,
                       gs_kt=gs, vrate_fpm=vr, on_ground=ground, squawk=squawk, nic=8, nac_p=9, sil=3, position_source="adsb",
                       source=Source.ADSBLOL)


def test_enrichment_operator_type_phase_airport():
    jfk = AIRPORTS["KJFK"]
    dep = enrich(_sv("a1", "DAL123", jfk.lat - 0.1, jfk.lon, 2500, 1800))  # south of JFK, over water: JFK is nearest
    assert (dep.operator_code, dep.operator_cat, dep.type_cat, dep.phase, dep.airport) == ("DAL", "airline", "narrowbody", "departure", "KJFK")
    app = enrich(_sv("a2", "JBU9", jfk.lat - 0.08, jfk.lon, 1500, -700))
    assert app.phase == "approach"
    arr = enrich(_sv("a3", "UAL84", jfk.lat - 0.45, jfk.lon, 7000, -1500))
    assert arr.phase == "arrival" and arr.airport == "KJFK"
    cruise = enrich(_sv("a4", "SWA1", 39.0, -100.0, 36000, 0))
    assert cruise.phase == "cruise" and cruise.airport is None
    grnd = enrich(_sv("a5", "N123AB", jfk.lat, jfk.lon, 13, 0, gs=5, ground=True, typ="C172", reg="N123AB"))
    assert grnd.phase == "ground" and grnd.operator_cat == "ga" and grnd.type_cat == "ga"
    mil = enrich(_sv("ae1", "HORSE60", 39.0, -100.0, 25000, 0, typ="K35R"))
    assert mil.operator_cat == "military" and mil.type_cat == "military"
    assert enrich(_sv("b1", "HBAL020", 39.0, -100.0, 60100, 0, gs=10, typ=None)).operator_cat == "balloon"


def test_phase_uses_field_elevation():
    den = AIRPORTS["KDEN"]  # 5,434 ft: 6,000 ft baro is only ~570 ft AGL
    sv = _sv("d1", "UAL1", den.lat, den.lon + 0.05, 6000, -600)
    assert phase_of(sv, den, 3.0)[0] == "approach"


def test_summarize_tables():
    jfk = AIRPORTS["KJFK"]
    states = [_sv("a1", "DAL123", jfk.lat - 0.1, jfk.lon, 2500, 1800), _sv("a2", "DAL456", jfk.lat - 0.3, jfk.lon, 6000, -900),
              _sv("a3", "UAL84", 39.0, -100.0, 36000, 0, squawk="7700"), _sv("a4", "N1", jfk.lat, jfk.lon, 13, 0, gs=3, ground=True, typ="C172", reg="N1")]
    b = Batch(ts=0, provider="p", region="r", states=states)
    enr = {sv.icao24: enrich(sv) for sv in states}
    s = summarize(b, enr, {}, faa_status=[{"airport": "JFK", "kind": "ground stop", "reason": "wind"}])
    a = next(r for r in s["airports"] if r["icao"] == "KJFK")
    assert a["departing"] == 1 and a["arriving"] == 1 and a["ground"] == 1 and a["faa"][0]["kind"] == "ground stop"
    ops = {r["code"]: r for r in s["operators"]}
    assert ops["DAL"]["aircraft"] == 2 and ops["DAL"]["compliance"] == 1.0 and ops["N"]["category"] == "ga"
    assert s["phases"]["cruise"] == 1 and s["categories"]["narrowbody"] == 3

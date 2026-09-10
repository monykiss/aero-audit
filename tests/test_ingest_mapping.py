from aero_audit.ingest.adsblol import map_aircraft
from aero_audit.ingest.opensky import map_row


def test_adsblol_ground_and_integrity():
    ac = {"hex": "AD3CF3", "flight": "JSX1121 ", "alt_baro": "ground", "gs": 12.0, "lat": 40.6,
          "lon": -73.8, "seen_pos": 1.5, "nic": 8, "nac_p": 10, "sil": 3, "type": "adsb_icao",
          "nav_altitude_mcp": 4000}
    sv = map_aircraft(ac, now_s=1000.0)
    assert sv.icao24 == "ad3cf3" and sv.on_ground and sv.baro_alt_ft is None  # never fabricate 0 ft on the ground
    assert sv.ts == 998.5 and sv.nic == 8 and sv.position_source == "adsb"
    assert sv.selected_alt_ft == 4000


def test_opensky_units():
    row = ["ac3688", "SWA3231 ", "United States", 1788982853, 1788982853, -73.8722, 40.7743,
           1000.0, False, 100.0, 106.88, 5.0, None, 1050.0, "4034", False, 0]
    sv = map_row(row, now_s=1788982900)
    assert abs(sv.baro_alt_ft - 3280.84) < 0.1
    assert abs(sv.gs_kt - 194.38) < 0.1
    assert abs(sv.vrate_fpm - 984.25) < 0.1
    assert sv.position_source == "adsb" and sv.lat == 40.7743


def test_endpoint_regions_exist_and_opensky_rejects_them():
    import asyncio

    import pytest

    from aero_audit.config import get_region
    from aero_audit.ingest.opensky import OpenSkyProvider

    assert get_region("mil").endpoint == "mil"
    p = OpenSkyProvider()
    with pytest.raises(ValueError):
        asyncio.run(p.fetch(get_region("mil")))
    asyncio.run(p.aclose())


def test_region_groups_expand_and_boxes_exist():
    from aero_audit.config import GROUPS, get_region, parse_regions

    hubs = parse_regions("usa-hubs")
    assert [r.key for r in hubs] == list(GROUPS["usa-hubs"]) and all(r.radius_nm == 250 for r in hubs)
    assert parse_regions("usa-hubs", 100)[0].radius_nm == 100
    conus = get_region("conus")
    assert conus.bbox() == (24.0, -125.0, 50.0, -66.0)
    from aero_audit.web.sources import region_catalog

    kinds = {r["key"]: r["kind"] for r in region_catalog()}
    assert kinds["usa-hubs"] == "group" and kinds["conus"] == "box" and kinds["mil"] == "global" and kinds["den"] == "us"

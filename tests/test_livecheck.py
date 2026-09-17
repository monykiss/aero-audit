"""The keyless live check with injected fetchers: every step reports, a failing feed does not hide the others, no account involved."""

import json
from pathlib import Path

from aero_audit.space import livecheck

ROOT = Path(__file__).parent.parent


def _tle(tmp_path: Path) -> Path:
    src = sorted((ROOT / "data/space/elements").glob("*.tle")) if (ROOT / "data/space/elements").is_dir() else []
    p = tmp_path / "els.tle"
    if src:
        p.write_text(src[-1].read_text())
    else:  # a single valid set is enough for the screen step
        p.write_text("ISS (ZARYA)\n1 25544U 98067A   26250.50000000  .00010000  00000-0  10000-3 0  9990\n2 25544  51.6400 247.4627 0006703 130.5360 325.0288 15.49000000123456\n")
    return p


def test_live_check_with_injected_fetchers(tmp_path):
    satcat_csv = tmp_path / "satcat.csv"
    satcat_csv.write_text("OBJECT_NAME,OBJECT_ID,NORAD_CAT_ID,OBJECT_TYPE,OPS_STATUS_CODE,OWNER,LAUNCH_DATE,LAUNCH_SITE,DECAY_DATE,PERIOD,INCLINATION,APOGEE,PERIGEE,RCS,DATA_STATUS_CODE,ORBIT_CENTER,ORBIT_TYPE\n"
                          "ISS (ZARYA),1998-067A,25544,PAY,+,ISS,1998-11-20,TYMSC,,92.96,51.63,423,416,399.0524,,EA,ORB\n")
    donki_json = tmp_path / "donki.json"
    donki_json.write_text(json.dumps({"notifications": [], "own_key": False}))

    def boom() -> Path:
        raise ConnectionError("launch library down")

    res = livecheck.run({"elements": lambda: _tle(tmp_path), "satcat": lambda: satcat_csv, "space_weather": lambda: ROOT / "data/samples/swpc_scales_sample.json",
                         "launches": boom, "donki": lambda: donki_json})
    by = {r["step"]: r for r in res["steps"]}
    assert [r["step"] for r in res["steps"]] == list(livecheck.STEPS)
    assert by["elements"]["ok"] and by["elements"]["sets"] >= 1
    assert by["satcat"]["ok"] and by["satcat"]["objects"] == 1
    assert by["space_weather"]["ok"] and by["space_weather"]["scales"]["G"] == 4 and "SWX-001" in by["space_weather"]["findings"]
    assert not by["launches"]["ok"] and "ConnectionError" in by["launches"]["error"]
    assert by["donki"]["ok"] and by["donki"]["agreement"]["G"] == "swpc-only"
    assert res["passed"] == 4 and res["total"] == 5 and res["spacetrack_used"] is False and res["all_keyless"]

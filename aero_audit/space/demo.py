"""One offline pass over every space and UAS analysis on the bundled samples: the portfolio demo and the smoke test
for the whole private branch. Each step writes a report with a manifest; the table at the end says what fired."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SAMPLES = Path("data/samples")


def run(out: str | Path = "reports", recording: str | Path | None = None, max_batches: int | None = None) -> list[dict[str, Any]]:
    from ..audit.generic_report import write_generic
    from ..space import debris, launches, spaceweather
    from ..space.cdm import assess as cdm_assess
    from ..space.cdm import parse_cdm
    from ..uas import encounter_model, extract_encounters, risk, summarize_encounters

    rec = Path(recording) if recording else SAMPLES / "adsblol_nyc_20260910T115129Z.jsonl.gz"
    rows: list[dict[str, Any]] = []

    def step(name: str, key: str, payload: Any, fs: list[Any], inputs: dict[str, Any]) -> None:
        paths = write_generic(out, name, key, payload, fs, inputs=inputs)
        rows.append({"step": name, "report": str(paths["json"]), "manifest": str(paths["manifest"]), "findings": len(fs), "rules": sorted({f.rule_id for f in fs})})

    m = debris.Mission.from_json(SAMPLES / "synthetic_mission.json")
    summary, fs = debris.checklist(m)
    step(f"debris_{m.name}", "summary", summary, fs, {"mission": SAMPLES / "synthetic_mission.json"})
    cdm = parse_cdm((SAMPLES / "synthetic_conjunction.cdm").read_text())
    res, fs = cdm_assess(cdm)
    step("cdm_synthetic", "assessment", res, fs, {"cdm": SAMPLES / "synthetic_conjunction.cdm"})
    payload = json.loads((SAMPLES / "swpc_scales_sample.json").read_text())
    summary, fs = spaceweather.assess(payload)
    exp, fs2 = spaceweather.exposed_flights(rec, summary["icao_advisory_conditions"], 40.0, max_batches)
    summary["exposed"] = exp
    step("space_weather", "summary", summary, fs + fs2, {"product": SAMPLES / "swpc_scales_sample.json", "recording": rec})
    payload = json.loads((SAMPLES / "ll2_launches_sample.json").read_text())
    summary, fs = launches.join_traffic(payload, rec, 250.0, max_batches=max_batches)
    step("launches", "summary", summary, fs, {"launches": SAMPLES / "ll2_launches_sample.json", "recording": rec})
    ex = extract_encounters(rec, max_batches=max_batches)
    summary, fs = summarize_encounters(ex)
    step(f"wellclear_{rec.stem.split('.')[0]}", "summary", summary, fs, {"recording": rec})
    summary, fs = risk.assess(rec, max_batches=max_batches)
    step(f"uas_risk_{rec.stem.split('.')[0]}", "summary", summary, fs, {"recording": rec})
    res = encounter_model.fit_and_simulate(rec, 500, max_batches=max_batches)
    step(f"encounter_model_{rec.stem.split('.')[0]}", "summary", res, [], {"recording": rec})
    return rows


__all__ = ["run"]

"""Gap fills: JSON telemetry loader, UTM external refs and contract fetch, NWS crisis extents, classifier evaluation on a hold-out."""

import json
from pathlib import Path

import numpy as np
import pytest

from aero_audit.ingest import nws_alerts
from aero_audit.space import telemetry
from aero_audit.uas import utm


def test_telemetry_json_loader_matches_csv_shape(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"time": [0, 1, 2, None], "velocity": [0.3, 12.0, 24.5, 30.0], "altitude": [0.0, 0.001, 0.004, 0.01], "acceleration": [11, 11, 12, 12]}))
    pts = telemetry.load_any(p)
    assert len(pts) == 3 and pts[1].speed_mps == 12.0 and pts[2].altitude_km == 0.004
    assert telemetry.audit_telemetry(pts) == []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"time": 1}))
    with pytest.raises(TypeError):
        telemetry.load_any(bad)
    real = Path("data/space/telemetry/gps3sv01_analysed.json")
    if real.is_file():
        pts = telemetry.load_any(real)
        assert len(pts) > 400 and max(p.speed_mps for p in pts) > 7000 and telemetry.audit_telemetry(pts) == []


def test_utm_external_refs_resolve_to_sibling_documents(tmp_path):
    (tmp_path / "geo.json").write_text(json.dumps({"definitions": {"Point": {"type": "object", "required": ["type", "coordinates"], "properties": {"type": {"type": "string", "enum": ["Point"]}, "coordinates": {"type": "array", "items": {"type": "number"}}}}}}))
    (tmp_path / "main.json").write_text(json.dumps({"swagger": "2.0", "definitions": {"Fix": {"type": "object", "required": ["loc"], "properties": {"loc": {"$ref": "https://example.org/x/geo.yaml#/definitions/Point"}}}}}))
    doc = utm.load_document(tmp_path / "main.json")
    assert utm.validate({"loc": {"type": "Point", "coordinates": [1.0, 2.0]}}, utm.schema_for(doc, "Fix"), doc) == []
    errs = utm.validate({"loc": {"type": "Line", "coordinates": [1.0]}}, utm.schema_for(doc, "Fix"), doc)
    assert errs and any("enum" in e or "Line" in e for e in errs)
    lone = {"definitions": {"A": {"$ref": "https://example.org/missing.yaml#/definitions/B"}}}
    with pytest.raises(ValueError, match="unresolvable"):
        utm.resolve_ref(lone, "https://example.org/missing.yaml#/definitions/B")
    if Path("data/uas/utm-domain-commons.json").is_file() and Path("data/uas/utm-domain-geojson.json").is_file():
        real = utm.load_document("data/uas/utm-domain-commons.json")
        good = json.loads(Path("data/samples/utm_position_sample.json").read_text())
        assert utm.validate(good, utm.schema_for(real, "Position"), real) == []
        bad = json.loads(Path("data/samples/utm_position_bad.json").read_text())
        assert len(utm.validate(bad, utm.schema_for(real, "Position"), real)) >= 3


def test_nws_alerts_summary_and_latest(tmp_path):
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-85, 40], [-84, 40], [-84, 41], [-85, 41], [-85, 40]]]},
                                                      "properties": {"event": "Flood Warning", "name": "Flood Warning: Somewhere"}}],
          "properties": {"fetched_at": "20260917T000000Z", "without_geometry": 2}}
    (tmp_path / "nws_alerts_20260917T000000Z.geojson").write_text(json.dumps(fc))
    p = nws_alerts.latest(tmp_path)
    assert p and p.name.startswith("nws_alerts_")
    s = nws_alerts.summary(p)
    assert s["features"] == 1 and s["by_event"] == {"Flood Warning": 1} and s["without_geometry"] == 2
    assert nws_alerts.latest(tmp_path / "none") is None
    from aero_audit.governance import run_study

    rec = run_study("ST-11", tmp_path / "studies", geojson=p)
    assert rec["result"]["extents"] == ["Flood Warning: Somewhere"]


def test_classifier_evaluate_on_a_second_manifest(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    from aero_audit.space import classifier, dataset

    monkeypatch.chdir(tmp_path)
    rng = np.random.default_rng(3)

    def make(root: Path, n: int, jitter: int) -> Path:
        items = []
        for label, base, pattern in (("red", (0, 0, 200), "stripes"), ("blue", (200, 0, 0), "plain")):
            d = root / "raw" / label
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                img = np.zeros((64, 64, 3), dtype=np.uint8)
                img[:] = base
                if pattern == "stripes":
                    img[::8, :, :] = 255
                img = np.clip(img.astype(int) + rng.integers(-jitter, jitter, img.shape), 0, 255).astype(np.uint8)
                p = d / f"{label}_{i}.png"
                cv2.imwrite(str(p), img)
                items.append(dataset.item(p, label, "synthetic", index=i))
        return dataset.write_manifest(items, root)

    train_m = make(tmp_path / "train", 14, 25)
    hold_m = make(tmp_path / "hold", 8, 40)  # same labels, noisier images: a second source
    out = tmp_path / "models" / "scene_classifier.joblib"
    classifier.train(train_m, out)
    model = classifier.load(out)
    ev = classifier.evaluate(hold_m, model, split=None)
    assert ev["n"] == 16 and 0.0 <= ev["accuracy"] <= 1.0 and set(ev["per_class"]) == {"red", "blue"} and sum(ev["confusion"].values()) == 16
    assert ev["verified"] and ev["model_feature_version"] == classifier.FEATURE_VERSION
    with pytest.raises(ValueError):
        classifier.evaluate(hold_m, model, split="nope")

"""Build a training frame from recordings, fit with a grouped holdout, and write a model card."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..features import TrackStore
from ..ingest.replay import iter_recording
from .anomaly import FEATURE_COLS, MIN_ALT_FT, KinematicAnomalyModel, frame_from_features


def features_from_recordings(paths: list[str | Path], window: int = 12) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    meta: dict[str, Any] = {"recordings": [], "providers": set(), "regions": set(), "first_ts": None, "last_ts": None, "polls": 0}
    for p in paths:
        store = TrackStore(window=window)
        feats = []
        for batch in iter_recording(p):
            feats.extend(store.update(batch))
            meta["providers"].add(batch.provider)
            meta["regions"].add(batch.region)
            meta["polls"] += 1
            meta["first_ts"] = batch.ts if meta["first_ts"] is None else min(meta["first_ts"], batch.ts)
            meta["last_ts"] = batch.ts if meta["last_ts"] is None else max(meta["last_ts"], batch.ts)
        df = frame_from_features(feats)
        df["recording"] = Path(p).name
        frames.append(df)
        meta["recordings"].append(Path(p).name)
    out = pd.concat(frames, ignore_index=True) if frames else frame_from_features([])
    meta["providers"], meta["regions"] = sorted(meta["providers"]), sorted(meta["regions"])
    return out, meta


def grouped_split(df: pd.DataFrame, holdout: float, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by aircraft, not by row, so the holdout contains unseen tracks."""
    rng = np.random.default_rng(seed)
    ids = df["icao24"].unique()
    rng.shuffle(ids)
    n_hold = int(len(ids) * holdout)
    hold_ids = set(ids[:n_hold])
    mask = df["icao24"].isin(hold_ids)
    return df[~mask], df[mask]


def _fmt(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%MZ") if ts else "-"


def model_card(stats: dict[str, Any], meta: dict[str, Any], model: KinematicAnomalyModel, holdout_top: list[dict[str, Any]]) -> str:
    q = stats["feature_quantiles"]
    lines = [
        f"# Model card: kinematic anomaly model ({stats['model_path']})",
        "",
        f"Trained {stats['trained_at']} with IsolationForest (300 trees, contamination {model.contamination}).",
        "",
        "## Intended use",
        (
            "Rank airborne ADS-B tracks by how unusual their pairwise kinematics are for the airspace the "
            "model was trained on. Output is an *investigation queue*, never an automatic action; the "
            "playbook for ML-001 forbids escalation on the model alone."
        ),
        "",
        "## Training data",
        f"- Recordings: {', '.join(meta['recordings'])}",
        f"- Providers: {', '.join(meta['providers'])}  Regions: {', '.join(meta['regions'])}",
        f"- Window: {_fmt(meta['first_ts'])} to {_fmt(meta['last_ts'])}  ({meta['polls']} polls)",
        (
            f"- Rows: {stats['samples_total']} airborne feature rows from {stats['aircraft_total']} aircraft "
            f"(filters: not on ground, baro altitude >= {MIN_ALT_FT:.0f} ft, both fixes have positions)"
        ),
        (
            f"- Split by aircraft: {stats['samples_train']} train rows / {stats['samples_holdout']} holdout rows "
            f"({stats['aircraft_holdout']} unseen aircraft)"
        ),
        "",
        "## Features",
        "| feature | p05 | p50 | p95 |",
        "|---|---|---|---|",
        *[f"| {c} | {q[c][0]:.1f} | {q[c][1]:.1f} | {q[c][2]:.1f} |" for c in FEATURE_COLS],
        "",
        "## Altitude bands",
        "| band | training rows | own pipeline | threshold |",
        "|---|---|---|---|",
        *[f"| {b} | {model.band_rows_.get(b, stats['samples_train'])} | {'yes' if b in model.pipelines else 'no (fallback)'} | "
          f"{model.thresholds_.get(b, model.thresholds_.get('all', 0)):.4f} |" for b in (*model.band_rows_.keys(), 'all')],
        "",
        "## Evaluation (unlabelled here; see `aero evaluate` for injected-scenario recall and precision)",
        f"- Threshold, fallback band (score quantile at contamination): {model.threshold_:.4f}",
        f"- Flag rate on training rows: {stats['flag_rate_train']:.2%}",
        (
            f"- Flag rate on holdout (unseen aircraft): {stats['flag_rate_holdout']:.2%}  "
            "(a holdout rate far above the contamination means the model over-fits the training aircraft)"
        ),
        "",
        "Top holdout anomalies and why:",
        *[f"- {r['icao24']} alt {r['baro_alt_ft']:.0f} ft, implied {r['implied_gs_kt']:.0f} kt vs reported "
          f"{r['reported_gs_kt']:.0f} kt; drivers {r['why']}" for r in holdout_top],
        "",
        "## Limitations",
        "- Pairwise features only; no memory of the whole track (a sequence model is on the roadmap).",
        "- Trained on a short window; diurnal and seasonal traffic patterns are not represented.",
        "- Helicopters, survey and aerobatic flights are legitimately anomalous and will recur.",
        "- Feed timestamp jitter dominates at dt < 5 s; such rows are noisy by construction.",
        "",
        "## Monitoring",
        "- Track ML-001 precision from analyst review; retrain when flag rate drifts > 2x contamination.",
        "- Regression-test with `tests/test_rules.py` (synthetic anomalies must stay detectable).",
    ]
    return "\n".join(lines)


def train(paths: list[str | Path], out: str | Path, contamination: float = 0.01, holdout: float = 0.2) -> dict[str, Any]:
    df, meta = features_from_recordings(paths)
    if len(df) < 50:
        raise ValueError(f"Only {len(df)} airborne feature rows; record more data first.")
    train_df, hold_df = grouped_split(df, holdout) if holdout > 0 else (df, df.iloc[0:0])
    model = KinematicAnomalyModel(contamination=contamination).fit(train_df)
    model.save(out)

    s_train = model.scores(train_df)
    stats: dict[str, Any] = {
        "trained_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ"),
        "contamination": contamination,
        "samples_total": len(df),
        "aircraft_total": int(df["icao24"].nunique()),
        "samples_train": len(train_df),
        "samples_holdout": len(hold_df),
        "aircraft_holdout": int(hold_df["icao24"].nunique()) if len(hold_df) else 0,
        "threshold": model.threshold_,
        "flag_rate_train": float((s_train < model.threshold_).mean()),
        "flag_rate_holdout": 0.0,
        "feature_quantiles": {c: [float(v) for v in np.nanquantile(df[c].astype(float), [0.05, 0.5, 0.95])] for c in FEATURE_COLS},
        "model_path": str(out),
    }
    holdout_top: list[dict[str, Any]] = []
    if len(hold_df):
        s_hold = model.scores(hold_df)
        stats["flag_rate_holdout"] = float((s_hold < model.threshold_).mean())
        expl = model.explain(hold_df)
        order = np.argsort(s_hold)[:5]
        for i in order:
            row = hold_df.iloc[int(i)]
            holdout_top.append({
                "icao24": row["icao24"], "baro_alt_ft": float(row["baro_alt_ft"] or 0),
                "implied_gs_kt": float(row["implied_gs_kt"] or 0), "reported_gs_kt": float(row["reported_gs_kt"] or 0),
                "why": expl[int(i)],
            })
    card_path = Path(out).with_suffix(".md")
    card_path.write_text(model_card(stats, meta, model, holdout_top))
    stats["model_card"] = str(card_path)
    stats["sha256"] = hashlib.sha256(Path(out).read_bytes()).hexdigest()
    _register(out, stats, meta)
    return stats


def _register(out: str | Path, stats: dict[str, Any], meta: dict[str, Any]) -> None:
    """Append provenance to models/registry.json so every model is traceable to its data."""
    reg = Path(out).parent / "registry.json"
    entries = json.loads(reg.read_text()) if reg.exists() else []
    entries.append({
        "trained_at": stats["trained_at"],
        "model_path": stats["model_path"],
        "sha256": stats["sha256"],
        "recordings": meta["recordings"],
        "providers": meta["providers"],
        "regions": meta["regions"],
        "rows": stats["samples_total"],
        "aircraft": stats["aircraft_total"],
        "contamination": float(stats.get("contamination", 0.0)),
        "features": FEATURE_COLS,
        "holdout_flag_rate": stats["flag_rate_holdout"],
        "evaluation": None,
    })
    reg.write_text(json.dumps(entries, indent=2))

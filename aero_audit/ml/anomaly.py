"""Unsupervised kinematic anomaly detection: IsolationForest per altitude regime.

Rules catch what we already know to look for. The model catches combinations that are merely
*unusual* for the airspace it was trained on. Terminal-area traffic (below 10,000 ft) and
en-route traffic have very different kinematic envelopes, so each altitude band gets its own
pipeline and threshold; an "all" pipeline is the fallback for bands with too little data.
Scores are calibrated to percentiles of the band's training distribution so downstream policy
can treat "1st percentile" the same way regardless of band or model version. Each finding
carries the top standardized feature deviations so an auditor can see *why* it was flagged.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..audit.findings import Category, Finding, Severity
from ..features import TrackFeatures

MIN_ALT_FT = 1000.0  # surface movement (taxi, takeoff roll) has its own physics; model it separately
MAX_DT_S = 120.0  # across longer gaps the pairwise features describe the gap, not the aircraft
MIN_BAND_ROWS = 300  # below this a band falls back to the "all" pipeline

FEATURE_COLS = [
    "implied_gs_kt",
    "reported_gs_kt",
    "gs_mismatch_kt",
    "gs_mismatch_ratio",
    "accel_kt_s",
    "implied_vrate_fpm",
    "reported_vrate_fpm",
    "vrate_mismatch_fpm",
    "turn_rate_dps",
    "window_gs_std_kt",
    "baro_alt_ft",
    "dt_s",
]

BANDS: dict[str, tuple[float, float]] = {"terminal": (0.0, 10000.0), "enroute": (10000.0, float("inf"))}
ALL = "all"


def frame_from_features(feats: Iterable[TrackFeatures], airborne_only: bool = True) -> pd.DataFrame:
    def _keep(f: TrackFeatures) -> bool:
        if not airborne_only:
            return True
        return (not f.on_ground and f.baro_alt_ft is not None and f.baro_alt_ft >= MIN_ALT_FT
                and f.dt_s <= MAX_DT_S)

    rows = [f.to_dict() for f in feats if _keep(f)]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["icao24", "ts", *FEATURE_COLS])
    for c in FEATURE_COLS:
        if c not in df:
            df[c] = np.nan
    return df


def _pipeline(contamination: float, random_state: int) -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("iforest", IsolationForest(n_estimators=300, contamination=contamination, random_state=random_state)),
        ]
    )


class KinematicAnomalyModel:
    def __init__(self, contamination: float = 0.01, random_state: int = 42) -> None:
        self.contamination = contamination
        self.random_state = random_state
        self.pipelines: dict[str, Pipeline] = {}
        self.thresholds_: dict[str, float] = {}
        self.train_scores_: dict[str, np.ndarray] = {}  # sorted, for percentile calibration
        self.n_train_: int = 0
        self.band_rows_: dict[str, int] = {}

    # -- helpers ----------------------------------------------------------------------------
    @staticmethod
    def band_of(alt: float | None) -> str:
        if alt is None or np.isnan(alt):
            return ALL
        for name, (lo, hi) in BANDS.items():
            if lo <= alt < hi:
                return name
        return ALL

    def _bands(self, df: pd.DataFrame) -> pd.Series:
        b = df["baro_alt_ft"].astype(float).map(self.band_of)
        return b.where(b.isin(self.pipelines.keys()), ALL)

    @property
    def threshold_(self) -> float | None:  # backward-compatible: the fallback band's threshold
        return self.thresholds_.get(ALL)

    # -- training ---------------------------------------------------------------------------
    def fit(self, df: pd.DataFrame) -> KinematicAnomalyModel:
        X_all = df[FEATURE_COLS].to_numpy(dtype=float)
        self.pipelines = {ALL: _pipeline(self.contamination, self.random_state).fit(X_all)}
        bands = df["baro_alt_ft"].astype(float).map(self.band_of)
        for name in BANDS:
            sub = df[bands == name]
            self.band_rows_[name] = len(sub)
            if len(sub) >= MIN_BAND_ROWS:
                self.pipelines[name] = _pipeline(self.contamination, self.random_state).fit(
                    sub[FEATURE_COLS].to_numpy(dtype=float)
                )
        for name, pipe in self.pipelines.items():
            sub = df if name == ALL else df[bands == name]
            sc = np.sort(pipe.score_samples(sub[FEATURE_COLS].to_numpy(dtype=float)))
            self.train_scores_[name] = sc
            self.thresholds_[name] = float(np.quantile(sc, self.contamination))
        self.n_train_ = len(X_all)
        return self

    # -- inference --------------------------------------------------------------------------
    def scores(self, df: pd.DataFrame) -> np.ndarray:
        """Lower = more anomalous (sklearn convention); each row scored by its band's pipeline."""
        out = np.zeros(len(df), dtype=float)
        bands = self._bands(df).to_numpy()
        X = df[FEATURE_COLS].to_numpy(dtype=float)
        for name in set(bands):
            m = bands == name
            out[m] = self.pipelines[name].score_samples(X[m])
        return out

    def thresholds_for(self, df: pd.DataFrame) -> np.ndarray:
        return self._bands(df).map(self.thresholds_).to_numpy(dtype=float)

    def percentiles(self, df: pd.DataFrame, scores: np.ndarray) -> np.ndarray:
        """Percentile of each score within its band's training distribution (0 = most anomalous)."""
        out = np.zeros(len(df), dtype=float)
        bands = self._bands(df).to_numpy()
        for name in set(bands):
            m = bands == name
            ref = self.train_scores_[name]
            out[m] = 100.0 * np.searchsorted(ref, scores[m], side="right") / max(len(ref), 1)
        return out

    def explain(self, df: pd.DataFrame, top_k: int = 3) -> list[list[tuple[str, float]]]:
        X = df[FEATURE_COLS].to_numpy(dtype=float)
        bands = self._bands(df).to_numpy()
        out: list[list[tuple[str, float]]] = [[] for _ in range(len(df))]
        for name in set(bands):
            m = np.where(bands == name)[0]
            Z = self.pipelines[name][:-1].transform(X[m])
            for i, row in zip(m, Z, strict=True):
                idx = np.argsort(-np.abs(row))[:top_k]
                out[int(i)] = [(FEATURE_COLS[j], round(float(row[j]), 2)) for j in idx]
        return out

    def findings(self, feats: list[TrackFeatures], ctx: Any) -> list[Finding]:
        if not self.pipelines:
            return []
        df = frame_from_features(feats)
        if df.empty:
            return []
        s = self.scores(df)
        thr = self.thresholds_for(df)
        pct = self.percentiles(df, s)
        expl = self.explain(df)
        bands = self._bands(df).to_numpy()
        out: list[Finding] = []
        for i, (_, row) in enumerate(df.iterrows()):
            if s[i] >= thr[i]:
                continue
            margin = thr[i] - s[i]
            sev = Severity.MEDIUM if margin > 0.05 else Severity.LOW
            out.append(
                Finding(
                    rule_id="ML-001",
                    title="Kinematic profile anomalous for this airspace (IsolationForest)",
                    severity=sev,
                    category=Category.ML,
                    icao24=str(row["icao24"]),
                    ts=float(row["ts"]),
                    evidence={
                        "anomaly_score": round(float(s[i]), 4),
                        "threshold": round(float(thr[i]), 4),
                        "anomaly_percentile": round(float(pct[i]), 2),
                        "band": str(bands[i]),
                        "top_deviations_z": expl[i],
                        "baro_alt_ft": row.get("baro_alt_ft"),
                        "implied_gs_kt": round(float(row.get("implied_gs_kt") or 0), 1),
                        "reported_gs_kt": row.get("reported_gs_kt"),
                        "position_source": row.get("position_source"),
                    },
                    controls=["Internal: model card + drift monitoring (NIST AI RMF MEASURE)"],
                    recommendation="Review the top deviating features; if benign, add to the "
                    "training window so the model learns the airspace's normal envelope.",
                )
            )
        return out

    # -- persistence ------------------------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> KinematicAnomalyModel:
        obj = joblib.load(path)
        if not isinstance(obj, cls):
            raise TypeError(f"{path} is not a KinematicAnomalyModel")
        return obj

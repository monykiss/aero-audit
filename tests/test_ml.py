import numpy as np
import pandas as pd

from aero_audit.ml.anomaly import ALL, FEATURE_COLS, KinematicAnomalyModel


def _frame(n, alt_lo, alt_hi, seed):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({c: rng.normal(size=n) for c in FEATURE_COLS})
    df["baro_alt_ft"] = rng.uniform(alt_lo, alt_hi, size=n)
    df["icao24"] = [f"x{i:05x}" for i in range(n)]
    df["ts"] = np.arange(n, dtype=float)
    return df


def test_band_models_fit_and_calibrate():
    df = pd.concat([_frame(400, 1000, 9000, 1), _frame(400, 12000, 40000, 2)], ignore_index=True)
    m = KinematicAnomalyModel(contamination=0.02).fit(df)
    assert set(m.pipelines) == {ALL, "terminal", "enroute"}
    s = m.scores(df)
    pct = m.percentiles(df, s)
    assert len(s) == len(df) and pct.min() >= 0 and pct.max() <= 100
    flagged = (s < m.thresholds_for(df)).mean()
    assert 0.005 < flagged < 0.05
    assert m.threshold_ == m.thresholds_[ALL]


def test_small_band_falls_back_to_all():
    df = pd.concat([_frame(400, 1000, 9000, 3), _frame(50, 12000, 40000, 4)], ignore_index=True)
    m = KinematicAnomalyModel().fit(df)
    assert "enroute" not in m.pipelines and "terminal" in m.pipelines
    assert (m._bands(df[df.baro_alt_ft > 10000]) == ALL).all()

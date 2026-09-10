# %% [markdown]
# # Exploring aero-audit recordings
# Run cell-by-cell in VS Code / Jupyter (`# %%` cells) or as a script:
# `.venv/bin/python notebooks/explore_recordings.py data/recordings/<file>.jsonl`

# %%
import sys
from pathlib import Path

import pandas as pd

from aero_audit.audit import AuditEngine
from aero_audit.features import TrackStore
from aero_audit.ingest import iter_recording
from aero_audit.ml import frame_from_features

path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(Path("data/recordings").glob("adsblol_*.jsonl"))[-1]
print("recording:", path)

# %% Flatten every state vector into a DataFrame
rows = []
for b in iter_recording(path):
    for sv in b.states:
        d = sv.model_dump()
        d["batch_ts"], d["region"] = b.ts, b.region
        rows.append(d)
df = pd.DataFrame(rows)
print(df.shape, "state vectors;", df.icao24.nunique(), "aircraft;", df.region.unique())

# %% Fleet mix and integrity distribution (adsb.lol only carries NIC/NACp/SIL)
print(df.aircraft_type.value_counts().head(10))
if df.nic.notna().any():
    air = df[(~df.on_ground) & df.position_source.fillna("").str.startswith("adsb")]
    print("share meeting 91.227 (NIC>=7, NACp>=8, SIL=3):",
          round(((air.nic >= 7) & (air.nac_p >= 8) & (air.sil >= 3)).mean(), 3))

# %% Kinematic features per fix (what the model and SEC-010/011 see)
store = TrackStore()
feats = []
for b in iter_recording(path):
    feats.extend(store.update(b))
fdf = frame_from_features(feats)
print(fdf[["implied_gs_kt", "reported_gs_kt", "gs_mismatch_kt", "turn_rate_dps", "dt_s"]].describe().round(1))

# %% Run the audit engine and look at the ranked findings
engine = AuditEngine()
engine.run(iter_recording(path))
s = engine.summary()
print(s["by_rule"])
top = sorted(engine.findings, key=lambda f: f.risk_score, reverse=True)[:10]
for f in top:
    print(f"{f.severity.value:8} {f.rule_id:8} {f.icao24} {f.callsign or '':9} {f.title}")

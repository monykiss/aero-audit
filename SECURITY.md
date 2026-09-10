# Security policy for aero-audit

## Scope and posture

aero-audit is a passive analysis tool. It receives public ADS-B data and imagery and produces
reports. It does not transmit RF, does not connect to aircraft, ATC, or airline systems, and
holds no credentials except optional OpenSky API client credentials in `.env`.

## Supply chain

- Dependencies are pinned in `requirements.lock.txt` (exact versions frozen from the working
  environment; `uv pip install -r requirements.lock.txt`). Regenerate `uv.lock` with `uv lock`
  when the network allows resolver access.
- Model weights (`yolov8n.pt`) are fetched from the ultralytics GitHub release on first use.
  Verify the checksum against the release page before use in a controlled environment, or
  vendor the file and pass `--weights`.
- Trained models (`models/*.joblib`) are pickles: load only files you produced.

## Data handling

- Recordings contain public broadcast data but enable tracking of individuals' aircraft.
  Apply retention limits and access control; honour `protect` watchlist entries.
- Never place credentials in recordings or reports; `.env` is git-ignored.

## Reporting a vulnerability

Open a private report to the repository owner. Include the recording (if any) that reproduces
the issue. Do not test injection or jamming against live aviation systems; use `aero synth` to
create synthetic recordings instead.

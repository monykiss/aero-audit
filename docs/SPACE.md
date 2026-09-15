# Space intake (private branch)

The delimited plan for the whole programme (air and space, compliance, risk, study, governing) is
[HOLISTIC_PLAN.md](HOLISTIC_PLAN.md); the governance layer it describes is `aero_audit/governance/` (`aero gov`).

This branch brings NASA open assets and launch footage into aero-audit with the same discipline as
the ADS-B side: every file has provenance, every stream gets physics checks, nothing is fetched
from a source whose terms are unclear. It stays on a local branch until it is ready to be offered
upstream (a catalogue and integrity tool for `nasa/NASA-3D-Resources`, or a NASA Image Library
client), so nothing here is public yet.

## Sources and terms

| Source | What | Terms | Module |
|---|---|---|---|
| [nasa/NASA-3D-Resources](https://github.com/nasa/NASA-3D-Resources) | 1,583 files, 5.3 GB: 257 glTF and 342 STL models, ~500 images and textures, split 7z archives | `meta.json`: NASA Open Source Agreement 1.3; README: "free and without copyright"; NASA media usage guidelines apply | `space/nasa3d.py` |
| [NASA Image and Video Library](https://images.nasa.gov) (`images-api.nasa.gov`) | Searchable imagery, video (with SRT captions and EXIF metadata), audio; includes SpaceX crew launches flown for NASA | Public domain in general; per-item `copyright` field must be honoured | `space/nasa_images.py` |
| Local footage you have rights to | Any video file | Yours | `space/footage.py` |
| Telemetry CSV | `t_s, speed, altitude` from an overlay reader, a flight-data export, or a simulation | Yours | `space/telemetry.py` |

SpaceX's own webcasts are copyrighted; this branch does not download them. The NASA library
carries NASA's coverage of those launches, which is what "footage like SpaceX" resolves to here.

## What works now

```bash
aero space catalog --subject 'ISS|Orion|SLS' --kind image      # list the repo without cloning 5 GB
aero space fetch 'ISS \(A\)' --kind image --max-mb 5            # verified download + provenance sidecar
aero space images 'Artemis II launch' --media video --limit 5   # search the NASA library
aero space images 'Crew-4 highlights' --media video --get 1 --variant captions   # fetch the SRT
aero space captions data/space/nasa_media/video/<id>/<id>.srt   # milestone timeline
aero space frames <video.mp4> --every 2 --detect                # frames + hashed manifest (+ detector)
aero space telemetry-audit flight.csv                           # SPC-001..005 physics checks
```

- **Catalogue with integrity.** The GitHub tree API gives every file's git blob SHA-1; a
  downloaded asset is accepted only when `sha1("blob <len>\0" + bytes)` matches, then written with
  a `.provenance.json` (URL, blob id, SHA-256, size, licence, time). Paths are confined to the
  destination directory.
- **Library client.** Search with media type, year and centre filters; renditions picked by name
  (`orig`, `large`, `medium`, `small`, `mobile`, `thumb`, `captions`, `metadata`); streamed download
  with a size cap, SHA-256 sidecar and a manifest; `verify_downloads()` re-hashes everything.
  Downloads are refused from any host other than `images-assets.nasa.gov`.
- **Footage.** Frames every N seconds with a manifest (video hash, per-frame hash, timestamp);
  captions parsed into a milestone timeline (liftoff, max-Q, MECO, separation, SECO, boostback,
  entry and landing burns, landing, deploy, abort) with the gaps between them; the existing tiled
  detector can run over frames.
- **Telemetry audit.** SPC-001 implausible acceleration (> 60 m/s²), SPC-002 altitude change faster
  than the reported speed allows, SPC-003 dropout (> 10 s), SPC-004 time regression or duplicate,
  SPC-005 altitude discontinuity (> 5 km per step). Findings use the toolkit's `Finding` model with
  evidence, controls and recommendations, and write JSON and Markdown reports.

## Orbital slice (phase 3, first cut)

```bash
aero space conjunctions --group stations --hours 24 --threshold-km 10     # keyless CelesTrak, SGP4, ORB-001..003
aero gov run-study ST-06 --tle data/space/elements/celestrak_stations_<stamp>.tle
```

Elements are fetched from CelesTrak with a provenance sidecar (source, time, SHA-256, set count),
checksummed per TLE convention, propagated with the MIT-licensed `sgp4` package (`[space]` extra),
and screened pairwise: coarse 60 s grid, fine 1 s pass around each candidate minimum. ORB-001 flags
sets older than seven days, ORB-002 an approach under the threshold (high under half of it),
ORB-003 SGP4 error codes. TLEs carry no covariance, so no probability of collision is claimed;
the screen tells you which CDMs to ask for. The lock file does not yet include `sgp4` (regenerate
with `make lock` when the network allows).

## Conjunction data messages (phase 3, second cut)

```bash
aero space cdm data/samples/synthetic_conjunction.cdm --hbr-m 20      # Pc from states + covariances, ORB-004/005
aero gov run-study ST-12 --cdm data/samples/synthetic_conjunction.cdm
```

`space/cdm.py` parses CCSDS 508.0-B KVN messages (header, relative metadata, two objects with
state vectors and RTN position covariances), rotates each covariance into the inertial frame
using that object's state, adds them, projects onto the encounter plane and integrates the 2D
Gaussian over the combined hard-body disc. The bundled `synthetic_conjunction.cdm` (labelled
synthetic: head-on LEO geometry, 50 m miss, 100 m sigmas) gives Pc about 1e-2, which the tests
check against the closed-form small-disc approximation. ORB-004 fires above 1e-4 (HIGH) or 1e-7
(MEDIUM); ORB-005 flags a stated miss distance that disagrees with the state vectors by more than
5 %, or a covariance that is not positive definite. Missing still: automated CDM intake and the
3D/long-encounter methods.

## Debris-mitigation checklist, CDM intake, Space-Track (phase 3, complete for supplied inputs)

```bash
aero space debris data/samples/synthetic_mission.json        # DEB-001..008 with a decay-model lifetime estimate
aero space cdm-inbox --inbox data/space/cdm/inbox            # KVN or XML messages -> ledger -> events with Pc trend
SPACETRACK_USER=... SPACETRACK_PASS=... aero space spacetrack --days 7   # public conjunction summaries into the ledger
aero gov run-study ST-13 --mission data/samples/synthetic_mission.json
```

`space/debris.py` checks a mission description against NASA-STD-8719.14 / ISO 24113 (and the
FCC five-year rule for US-licensed LEO): post-mission lifetime from a piecewise exponential
atmosphere decay integration (stated factor-of-two uncertainty), passivation, collision-avoidance
capability in populated shells, reentry casualty risk, GEO graveyard raise, trackability, planned
releases, large-constellation disposal reliability. `space/cdm_inbox.py` parses KVN and CCSDS XML
messages, assesses each (Pc, ORB-004/005), keeps an append-only ledger keyed by message id and
content hash, and groups messages into events per pair and TCA with the trend of Pc.
`space/spacetrack.py` pulls `cdm_public` summaries and GP elements behind a free account, cached
with provenance; summaries carry the stated Pc and are never recomputed (no covariance).

## Training data and the scene classifier (phase 1, honest baseline)

```bash
aero space dataset --per-class 30 --nasa3d-catalog data/space/nasa3d_catalog.json   # NASA library + 3D previews, hashed, split
aero space classify-train data/space/dataset/manifest.json                            # card + registry entry
aero space classify data/space/frames/<video>/frames.manifest.json                    # scene per frame
scripts/train_detector.py data/space/dataset/manifest.json                            # ultralytics fine-tune when installed
```

`space/dataset.py` builds labelled datasets from NASA library searches (items with a copyright
field are excluded) and from NASA-3D model previews labelled by subject family, with per-item
SHA-256, attribution, and a deterministic train/validation split by content hash.
`space/classifier.py` is a colour-histogram plus gradient-orientation logistic regression, trained
and evaluated on the manifest splits, saved with a model card and a registry entry behind the same
checksum gate as the anomaly model. It labels scenes (launch, orbit, station, surface); it is not
a detector. `scripts/train_detector.py` lays the dataset out for ultralytics and runs the fine-tune
when that extra is installed.

## Space weather, launch windows, scheduled intake (cross-domain)

```bash
aero space weather                                   # NOAA scales + Kp (keyless) -> ICAO advisory conditions, SWX-001..004
aero space weather --recording <rec> --lat-min 60    # plus the flights exposed poleward of 60° (SWX-005)
aero space launches --recording <rec>                # Launch Library 2 windows joined to traffic near the pad, LCH-001..003
aero space watch --schedule cdm_inbox=600,space_weather=900,launches=3600   # headless scheduled intake
AERO_SCHEDULE=cdm_inbox=600,space_weather=900 aero app                      # the same inside the web app
aero accounts                                        # which services are configured; values never printed
```

`space/spaceweather.py` maps NOAA's R / S / G levels onto the two ICAO Annex 3 advisory levels
per effect (the mapping is in the module and in every report); G and S conditions also list the
high-latitude aircraft in a recording, because the same storm degrades ADS-B integrity fields,
HF on polar routes and drag on LEO objects. `space/launches.py` reduces Launch Library 2 records
to windows and pads and counts aircraft inside a hazard radius during each window that overlaps a
recording, with the traffic outside the window as the displacement baseline; the NOTAM geometry
stays authoritative. `web/schedule.py` runs any registered job on an interval as an ordinary,
audited job (network jobs are skipped under `AERO_OFFLINE=1`), and `web/space_jobs.py` is the one
registry the app, the scheduler and `aero space watch` share. The SPACE page in the app shows all
of it with buttons that submit the same jobs.

## Renders, element history (depth items)

```bash
aero space render <model.obj> --label iss --n-yaw 12 --manifest data/space/dataset/manifest.json   # 36 silhouette views into the dataset
aero space maneuvers                                  # every cached element file: ORB-006 manoeuvre-scale change, ORB-007 decay imminent
aero gov run-study ST-20 --tle a.tle --tle b.tle      # element history study
```

`space/render.py` is a numpy z-buffer rasteriser for Wavefront OBJ (polygons fanned, two-sided
Lambert, orthographic): many viewpoints of one spacecraft with a manifest carrying the model hash
and view parameters, appended to the dataset as `nasa3d-render` items. It gives shape and
silhouette, not texture; the 3DS and LWO models in NASA-3D-Resources need a converter first.
`space/maneuvers.py` compares mean elements of the same object across cached snapshots: a
semi-major-axis rise, or a fall beyond what drag explains per day, or an inclination step is a
manoeuvre (ORB-006, so approaches computed from the older set are void); a perigee under 200 km
or a mean-motion derivative implying re-entry within 30 days is ORB-007. Thresholds are stated in
every report; TIP messages from the tracking authority remain the reentry reference.

## Demo and evidence

```bash
aero space demo            # debris, CDM, space weather, launches, well-clear, risk classes, encounter model on the samples
aero doctor                # adds space rows: sgp4, OpenCV, cached elements, CDM ledger, samples
aero log bundle            # the evidence zip carries every report, its Markdown and its manifest
```

Every report on this branch is three files: the JSON the pages read, a Markdown rendering, and a
manifest with SHA-256 of both plus provenance (tool version, commit, Python, platform, input files
and their hashes). `aero log verify-report <manifest>` re-hashes them; the Reports page links all three.

## Honest limits

- The COCO detector has no "rocket" class. Frame detection stays a placeholder until the ultralytics
  fine-tune in `scripts/train_detector.py` is run on the dataset; the scene classifier covers
  segmentation, not detection.
- Debris lifetimes are estimates from a simple decay model, not certified analyses; Space-Track
  summaries carry the originator's Pc only.
- The ICAO mapping of NOAA scales is a programme choice; the advisory centres apply the normative
  thresholds. The launch hazard radius is a default, not the published TFR.
- Telemetry must be supplied as CSV. Reading the numbers off a webcast overlay (OCR) is not
  implemented; when it is, it stays optional (tesseract) and its output is audited by the same rules.
- The GitHub tree API is rate-limited to 60 calls an hour anonymously; set `GITHUB_TOKEN` for more.

## Toward an upstream contribution

The catalogue and verification tool is generic: a JSON manifest of every asset with its blob id,
size, kind and subject, plus a verified fetch. Offered upstream it would let users of
`NASA-3D-Resources` pick assets without cloning the repository and prove their copies are intact.
Before proposing it: rename the CLI to stand alone, add a `--format csv` output, write the
contribution note the NASA repo asks for, and confirm the licence text with the point of contact
in `meta.json`.

## Branch hygiene

`git config branch.space-intake.pushRemote` is set to a non-existent remote, so `git push` on this
branch fails by design. Merge into `main` only after the licence questions above are settled.
`data/space/` is git-ignored: fetched assets, frames and reports never enter version control.

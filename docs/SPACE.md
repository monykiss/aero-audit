# Space intake (private branch)

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

## Honest limits

- The COCO detector has no "rocket" class. Frame detection is a placeholder until a detector is
  fine-tuned; the NASA 3D models (rendered from many angles) plus library imagery are the intended
  training set. That is the next ML task on this branch.
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

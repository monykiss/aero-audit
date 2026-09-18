# Performance (private branch)

Measured on the development laptop (Apple Silicon, Python 3.12, numpy), best of three, with
`aero bench --suite space` and the CLI commands named. Every rewrite keeps the scalar version in
the module as `_..._reference` and `tests/test_perf_equivalence.py` proves the two agree: the
projection on 6,000 random geometries, the rasteriser bit for bit with and without chunking, the
conjunction screen pair by pair on a synthetic shell with a planted close pair.

## Before and after (2026-09-15)

| Hot path | Input | Before | After | How |
|---|---|---|---|---|
| Well-clear scoring, `aero uas wellclear` | CONUS recording, 8,322 aircraft, 30,641 pairs | ~60 s | 11 s | the time-to-violation projection evaluates the whole horizon grid with numpy instead of one `violates()` call per second of look-ahead (three levels per pair-sample) |
| Projection alone | 2,000 geometries × 3 alert levels | 50 s-steps each in Python | 50,000 projections/s | same |
| Rasteriser, `aero space render` | 39,600-triangle sphere at 256 px | 1.11 s | 0.04 s | every (triangle, bounding-box pixel) pair generated with repeat/cumsum, barycentrics in one shot, `np.maximum.at` z-buffer, chunked at 4 M candidate pixels |
| Conjunction screen, `aero space conjunctions` | 120 objects, 7,140 pairs, 6 h at 60 s | Python double loop over pairs × samples | 0.04 s (167,000 pairs/s) | `SatrecArray` propagation to an (n, samples, 3) array; one broadcasted distance and `nanargmin` per object; fine pass only for candidates, propagated as arrays |
| Catalogue build, `aero data catalog build` | 176 granules | hash every file each build | 0.17 s warm | size + mtime hash cache in `data/app/catalog_hashes.json`; a changed file re-hashes, a `hash_cache=None` build ignores it |
| TFR traffic join, `aero space tfr --recording` (1.0) | 2 restrictions × 2,328 state vectors (12 batches) | new | 0.015 s (304,000 point-in-volume tests/s) | planar ray casting per fix with the altitude gate first; features filtered to those with geometry once per run |
| Reentry subpoints, `aero space reentry` (1.0) | 120 objects × 721 samples (6 h at 30 s) | new | 0.029 s (3.0 M subpoints/s) | `SatrecArray` propagation to an (n, samples, 3) array, GMST and the geodetic iteration vectorised over the whole grid |
| Space and UAS pages | polled every 3 s | rescanned reports and reassessed cached products per request | memoised 5 s | `web/views._memo` |

The rules engine benchmark (`aero bench`) is unchanged by this work; its numbers live in the
public branch's `reports/bench_*.json`.

## What this buys

- A national recording scores for well-clear in the time it takes to read it, so ST-07/ST-08/ST-16
  can run on every capture rather than on samples.
- Rendering the 36-view set for a 1 M-triangle NASA model is minutes, not hours, on a laptop.
- A full CelesTrak group (a few hundred objects) screens in seconds; the O(n²) is now in numpy.

## Still scalar, on purpose

- The per-pair Python loop in `extract_encounters` that walks cell neighbourhoods: it filters by
  range and altitude before any projection runs, and the profile shows the projection, not the
  walk, dominated. Revisit if recordings exceed ~20,000 airborne aircraft per batch.
- The fine pass of the screen per candidate pair (a handful of pairs per screen).
- The CDM probability-of-collision integration (2D polar grid): one message at a time, milliseconds.

Reproduce: `aero bench --suite space --rounds 3` writes `reports/bench_space_<stamp>.json`.

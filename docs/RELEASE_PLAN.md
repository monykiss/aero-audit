# Release plan for the private branch

The branch stays local until you decide otherwise (policy P-08). This page makes that decision
cheaper by saying what each part of the branch depends on, so the one open question, the licence
answer from the NASA-3D-Resources maintainers, blocks only the parts that actually touch that repository.

## Three slices

| Slice | What it holds | Depends on | Blocked by the licence question? |
|---|---|---|---|
| **A. Governance and air/space analytics** | governance package (domains, standards, controls, register, studies, posture, assurance, catalogue, traceability, publish-check, status), UAS (well-clear, encounters, risk classes, encounter model, trend, UTM contracts), orbital (CelesTrak elements, SGP4 screen, CDM inbox and Pc, manoeuvres, debris rules), space weather (NOAA, DONKI), launch windows, SATCAT, scheduler, Space and UAS pages, generic reports, performance work | keyless public feeds with permissive or public-domain terms (CelesTrak citation, NOAA public domain, The Space Devs attribution, api.nasa.gov open data); synthetic samples | **No** |
| **B. NASA open assets** | `space/nasa3d.py` (catalogue and blob-verified fetch), `space/nasa_images.py` (library client), `space/footage.py`, `space/dataset.py` (library and preview datasets), `space/mesh.py` and `space/render.py` when run on NASA models, the scene classifiers trained on library imagery, `scripts/nasa3d_catalog.py`, `docs/UPSTREAM.md` | NASA-3D-Resources terms (meta.json names NOSA 1.3 and "free and without copyright"), NASA media guidelines, library items' per-item copyright field | **Partly**: the code is ours and publishable; redistributing NASA models, renders of them, or library images inside the repository is what the licence answer settles. Cached data is git-ignored already |
| **C. Optional accounts** | Space-Track client and the restricted-row handling, OpenSky credentials, NASA API key | the user's accounts; Space-Track's user agreement (no redistribution of its data or analyses) | **No** for code; Space-Track-derived data never enters the repository (PUB-11) |

Slice A is 80% of the branch by lines and all of its measurable claims. Slice B's *code* is
publishable today; what it must not do without the answer is ship NASA-derived artefacts.

## Recommendation

Publish **slice A and C together with slice B's code, but without any NASA-derived data**, as **0.7.0**,
the day the licence answer arrives; if no answer comes within a month, publish the same set anyway,
because nothing in it redistributes NASA material (the repository is already free of NASA assets: they
live under git-ignored `data/space/`). Merging everything at once avoids a refactor that exists only to
hold back code that is ours. The upstream pull request to NASA-3D-Resources stays separate and waits.

`scripts/release_candidate.sh 0.7.0` prepares that release on a local, push-guarded branch: version
bump, changelog heading, generated docs, suite, and the publication gate. It stops before pushing and
prints the two commands that publish.

## Decision points (yours)

1. **Send the licence email** in `docs/UPSTREAM.md`. Until then nothing in slice B ships data.
2. **Choose the public shape** when the answer arrives:
   - *Merge everything into `main`* and release 0.7.0: simplest; the README already has the branch quick start.
   - *Merge slices A and C now, hold B*: needs a small refactor to make the `space` package import cleanly without `nasa3d`/`nasa_images` (they are only imported inside functions today, so this is mostly moving three CLI commands behind a flag).
   - *Keep it private as a portfolio branch*: nothing to do; `aero gov publish-check --strict` documents why.
3. **Name the version**: 0.7.0 for A alone, 1.0.0 if B ships with the upstream contribution accepted.

## Mechanical gate

`aero gov publish-check --strict` must pass before any push of the branch. It fails today on exactly
one item, PUB-10 (the licence answer), and on nothing else. Rerun it after the answer, then:

```bash
git checkout space-intake && aero gov publish-check --strict && git push -u origin space-intake
```

That command sequence is the only one that lifts the push guard (`branch.space-intake.pushRemote=no_push`);
remove the guard the same day with `git config --unset branch.space-intake.pushRemote`.

## What a public release would carry

- Version bump, changelog section from "Unreleased (space-intake, private branch)".
- CI: the lock already pins `sgp4`; the `vision` extra (OpenCV, ultralytics, DracoPy) stays optional and
  its tests skip in CI as they do now.
- Docs: `docs/SPACE.md`, `docs/UAS.md`, `docs/ACCOUNTS.md`, `docs/PERFORMANCE.md`, `docs/HOLISTIC_PLAN.md`,
  generated STATUS, TRACEABILITY, ASSURANCE, CONTROLS, STUDIES, POSTURE, API.
- Release assets as for 0.6.0 (wheel, sdist, SBOM, checksums, Sigstore).

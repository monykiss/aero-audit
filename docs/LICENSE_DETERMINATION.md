# Licence determination for the NASA-3D-Resources work

Recorded 2026-09-18 from the sources named below, so the decision does not depend on an answer to
the courtesy email in `docs/upstream_email.txt`.

## Facts, with where they come from

1. `nasa/NASA-3D-Resources` has **no LICENSE file** (HTTP 404 for `LICENSE` and `LICENSE.md` on the
   default branch, checked 2026-09-18).
2. Its `meta.json` states `"license": "NASA Open Source Agreement Version 1.3"` and names the point of
   contact `arc-special-proj@lists.nasa.gov`.
3. Its `README.md` states: "These assets are free and without copyright." and points to NASA's usage
   guidelines at https://www.nasa.gov/nasa-brand-center/images-and-media, which allow use of NASA
   imagery and models for educational and informational purposes and restrict the NASA insignia, any
   implication of endorsement, and identifiable people.
4. The NASA Open Source Agreement 1.3 is an OSI-approved licence for NASA-released software. It governs
   modification and redistribution of the *software* and contributions to it; it is not GPL-compatible.
5. NASA works are generally not subject to copyright in the United States (17 U.S.C. 105); the README's
   wording restates that for these assets.
6. The NASA image library items used for the scene dataset carry a per-item copyright field; the dataset
   builder excludes any item with that field set (`space/dataset.py`).
7. Space-Track material is a separate question, settled separately: its user agreement forbids
   redistribution of data or analyses, and the tool marks and excludes it (`docs/ACCOUNTS.md`, PUB-11).

## Determination

- **Our code** (everything under `aero_audit/`, `scripts/`, `tests/`, `docs/`) is ours and MIT-licensed as the
  rest of the repository. Nothing in it is derived from NASA source code.
- **NASA assets** (models, previews, library images) are cached under git-ignored `data/space/` and are
  **never redistributed** by this repository. Renders and datasets built from them stay local for the
  same reason, although the assets' own terms would permit redistribution with attribution and without
  insignia or endorsement. The attribution file names every source and its terms.
- **The upstream contribution** (`scripts/nasa3d_catalog.py` and a generated `CATALOG.json`) is offered
  under **NOSA 1.3**, the licence the repository declares, and carries no NASA content itself: it lists
  file names, sizes and git blob ids obtained from GitHub's public API.

Decision: **licence position determined; no NASA material is redistributed; the contribution goes under
NOSA 1.3.** The email remains a courtesy and a request for the preferred file location; its answer
cannot change the determination above, only the shape of the pull request.

## What this unblocks

- Publication gate PUB-10 passes on this document (it checks for the Determination and Decision lines).
- The upstream pull request can be opened when you say so; it needs a public fork under your account,
  which is why it waits for your word.

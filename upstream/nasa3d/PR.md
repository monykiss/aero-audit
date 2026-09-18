# Contribution package for nasa/NASA-3D-Resources (kept here, not in a fork)

This directory is the complete, self-contained contribution: `nasa3d_catalog.py` (Python 3.9+, standard
library only), `CATALOG.json` (generated from the GitHub tree API on the date in its `generated_at`
field) and the `README.md` that would sit beside them under `tools/`. It was offered as
nasa/NASA-3D-Resources pull request #50 on 2026-09-18 and withdrawn the same day, because the
maintainer of this repository keeps only `aero-audit` public and a fork under the account was not wanted.

To offer it again, the maintainer forks the repository themselves, copies these three files to
`tools/`, and opens the pull request with the text in `docs/UPSTREAM.md`. Regenerate `CATALOG.json`
on the day (`python3 nasa3d_catalog.py catalog --out CATALOG.json`) and run `verify` on three files.

Licence: offered under the repository's declared terms (NASA Open Source Agreement 1.3, `meta.json`);
see `docs/LICENSE_DETERMINATION.md`.

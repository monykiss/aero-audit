# Upstream package for nasa/NASA-3D-Resources

What we would offer, in the shape their repository can take, once the licence wording is
confirmed with the contact in `meta.json` (`arc-special-proj@lists.nasa.gov`).

## The offer

A generated `CATALOG.json` plus `scripts/nasa3d_catalog.py` (standard library only), giving
users of the repository three things they ask for in the issue tracker:

- **Find without cloning.** The catalogue lists every file with size, git blob id, kind (model,
  image, archive, doc) and subject folder, built from the GitHub tree API, so someone wanting one
  ISS model does not need the 5 GB clone.
- **Verify what you downloaded.** `verify <path>` recomputes git's blob hash of the fetched bytes
  and compares it with the tree, so a corrupted or substituted download is caught.
- **Answer #43 and #44.** `summary` prints the model subjects that have no preview image (issue
  #43, "LWO version missing images") and the kind classification surfaces files in the wrong
  folder (issue #44, "Miscategorization of a file").

## Draft pull-request text

> **Add a machine-readable catalogue and a verification script**
>
> This adds `CATALOG.json` (generated, 1,583 files, 5.3 GB, 374 subjects) and
> `tools/nasa3d_catalog.py`, a dependency-free script that regenerates the catalogue from the
> GitHub tree API, prints model subjects without a preview image, and verifies a downloaded file
> against its git blob id.
>
> Motivation: users who need one model currently clone the whole repository; issues #43 and #44
> are both questions the catalogue answers directly. No existing files are modified; the script is
> Python 3.9+ standard library and runs in a few seconds.
>
> Licence: the script is offered under the repository's terms (NASA Open Source Agreement 1.3 per
> `meta.json`). Please confirm that is the intended licence for contributions, and whether the
> catalogue should live at the root or under `tools/`.

## Before sending

1. Confirm the licence with the point of contact (email above) and note the answer here.
2. Regenerate the catalogue from the current default branch on the day of the PR.
3. Run `scripts/nasa3d_catalog.py verify` on three files of different kinds and paste the output.
4. Keep the PR to the script and the catalogue: no aero-audit code, no renamed files.

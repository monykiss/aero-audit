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

## Status

**Withdrawn 2026-09-18.** Pull request nasa/NASA-3D-Resources#50 was opened from a fork under the
maintainer's account and closed the same day with a note, because the maintainer keeps only `aero-audit`
public; the fork is archived pending deletion. The complete package now lives in `upstream/nasa3d/`
(script, generated catalogue, README, and `PR.md` with the resubmission steps). The determination in
`docs/LICENSE_DETERMINATION.md` stands.

## Before sending

1. Licence: **determined 2026-09-18** in `docs/LICENSE_DETERMINATION.md` (NOSA 1.3 for the contribution; nothing NASA-owned redistributed). The email below is a courtesy about the preferred location of CATALOG.json.
2. Regenerate the catalogue from the current default branch on the day of the PR. **Done 2026-09-16** (below).
3. Run `scripts/nasa3d_catalog.py verify` on three files of different kinds and paste the output. **Done 2026-09-16** (below).
4. Keep the PR to the script and the catalogue: no aero-audit code, no renamed files.

### Catalogue run, 2026-09-16

```
$ scripts/nasa3d_catalog.py catalog --out CATALOG.json
1195 files, 5.00 GB, 374 subjects, by kind {'model': 622, 'image': 508, 'archive': 45, 'other': 5, 'doc': 15}
$ scripts/nasa3d_catalog.py summary
374 subjects; 0 model subjects without a preview image
```

Model formats in the tree: STL 342, GLB 257 (Draco-compressed), Blender 13, LightWave 4, 3DS 4, FBX 2.
Issue #43 (missing preview images) no longer reproduces on the current default branch; the PR text
should say so rather than claim to fix it.

### Verify run, 2026-09-16

```
OK 3D Models/TOPEX-Poseidon/TOPEX-Poseidon.lwo (338480 bytes) blob 92dd9fc64668 expected 92dd9fc64668
OK 3D Printing/International Space Station Tools/003 - Column.stl (684 bytes) blob bbf44d419dd8 expected bbf44d419dd8
OK 3D Models/International Space Station (ISS) (A)/International Space Station (ISS) (A).png (429092 bytes) blob 311f1d272e76 expected 311f1d272e76
```

### Licence email (for you to send to arc-special-proj@lists.nasa.gov)

> Subject: NASA-3D-Resources: contribution licence question and a small catalogue/verify tool
>
> Hello,
>
> I maintain a small open-source auditing toolkit and would like to contribute a dependency-free
> Python script and a generated catalogue (CATALOG.json) to nasa/NASA-3D-Resources. The script
> regenerates the catalogue from the GitHub tree API, lists model subjects without a preview image,
> and verifies a downloaded file against its git blob id, so users who need one model do not have
> to clone the 5 GB repository.
>
> meta.json names the NASA Open Source Agreement 1.3. Before opening a pull request I would like to
> confirm (1) that NOSA 1.3 is the intended licence for contributions to this repository, and (2)
> whether a generated catalogue file at the root, or under tools/, is acceptable. I am happy to
> sign whatever contributor paperwork the agreement requires.
>
> Thank you,
> <your name>

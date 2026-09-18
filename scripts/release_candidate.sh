#!/usr/bin/env bash
# Prepare (never push) a release candidate of the private branch: a local branch with the version bumped, the changelog
# heading set, generated docs rebuilt, the full suite and the publication gate run. Stops before any push; the push
# sequence is printed at the end and is a human decision (docs/RELEASE_PLAN.md).
#   scripts/release_candidate.sh 0.7.0
set -euo pipefail
VERSION="${1:?usage: scripts/release_candidate.sh <version>}"
cd "$(dirname "$0")/.."
git diff --quiet || { echo "working tree not clean"; exit 1; }
git checkout -q space-intake
git branch -f "release-$VERSION" space-intake
git checkout -q "release-$VERSION"
git config "branch.release-$VERSION.pushRemote" no_push
python3 - "$VERSION" <<'PY'
import re, sys
from pathlib import Path
v = sys.argv[1]
p = Path("aero_audit/__init__.py"); s = p.read_text(); s = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{v}"', s); p.write_text(s)
p = Path("pyproject.toml"); s = p.read_text(); s = re.sub(r'^version = "[^"]+"', f'version = "{v}"', s, count=1, flags=re.M); p.write_text(s)
p = Path("CHANGELOG.md"); s = p.read_text()
import datetime as dt
s = s.replace("## Unreleased (space-intake, private branch)", f"## {v} - {dt.date.today().isoformat()}", 1); p.write_text(s)
print("bumped to", v)
PY
.venv/bin/aero docs-build >/dev/null
.venv/bin/ruff check aero_audit tests scripts
.venv/bin/python -m pytest -q | tail -1
git add -A && git commit -q -m "release candidate $VERSION (local; not pushed)" || true
echo
echo "Release candidate on branch release-$VERSION (push guard set)."
.venv/bin/aero gov publish-check --strict || true
echo
echo "To publish (a human decision):"
echo "  git config --unset branch.release-$VERSION.pushRemote && git push -u origin release-$VERSION"
echo "  then open the PR into main, tag v$VERSION after merge; the release workflow builds wheel, sdist, SBOM, checksums, Sigstore."

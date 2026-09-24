"""The recordings inventory resumes from where it last read.

A capture that is still running grows between requests. The inventory used to key its cache on size and
mtime, which an append changes every time, so the whole file was re-parsed on every call. These cover the
resume path: same answer as a full read, only the new bytes touched, and a rewrite still forces a re-read.
"""

import json

from aero_audit.synthetic import generate
from aero_audit.web import app as app_mod
from aero_audit.web.app import App

PUBLIC = ("file", "provider", "regions", "polls", "state_vectors", "aircraft", "first_ts", "last_ts", "span_min", "special")


def _tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AERO_SCHEDULE", "")
    (tmp_path / "data/recordings").mkdir(parents=True)
    (tmp_path / "data/samples").mkdir(parents=True)


def _app():
    app = App()
    app.scheduler.stop()
    app.sources.stop()
    return app


def _only(app):
    return next(r for r in app.recordings() if r["file"] == "nyc.jsonl")


def _append(path, polls, start_ts):
    """Extra batches in the recorder's own format, appended to a finished file."""
    extra = generate(path.with_name("extra.jsonl"), n_aircraft=8, polls=polls, start_ts=start_ts)
    with open(path, "a") as fh:
        fh.write(extra.read_text())
    extra.unlink()


def test_resumes_from_the_stored_offset_and_matches_a_full_read(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    rec = tmp_path / "data/recordings/nyc.jsonl"
    generate(rec, n_aircraft=8, polls=5, start_ts=1_700_000_000.0)

    app = _app()
    first = _only(app)
    assert first["polls"] == 5

    starts = []
    real = app_mod._iter_batches
    monkeypatch.setattr(app_mod, "_iter_batches", lambda f, start: (starts.append(start), real(f, start))[1])

    _append(rec, polls=4, start_ts=1_700_001_000.0)
    grown = _only(app)

    assert starts and starts[-1] > 0, "the appended bytes were read, the prefix was not"
    assert grown["polls"] == 9

    # A cold app re-reads the whole file: the resumed summary must be identical to it.
    (tmp_path / "data/app/inventory.json").unlink()
    assert {k: grown[k] for k in PUBLIC} == {k: _only(_app())[k] for k in PUBLIC}


def test_an_unchanged_file_is_not_read_again(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    generate(tmp_path / "data/recordings/nyc.jsonl", n_aircraft=8, polls=5)
    app = _app()
    _only(app)
    monkeypatch.setattr(app_mod, "_iter_batches", lambda f, start: (_ for _ in ()).throw(AssertionError("re-read an unchanged file")))
    assert _only(app)["polls"] == 5


def test_a_half_written_record_waits_for_the_rest_of_its_line(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    rec = tmp_path / "data/recordings/nyc.jsonl"
    generate(rec, n_aircraft=8, polls=5, start_ts=1_700_000_000.0)
    app = _app()
    assert _only(app)["polls"] == 5

    _append(rec, polls=2, start_ts=1_700_001_000.0)
    whole = rec.read_text()
    cut = whole.rindex("\n", 0, whole.rindex("\n")) + 1  # keep the second-to-last newline, drop the last
    rec.write_text(whole[:cut] + whole[cut:].rstrip("\n"))

    assert _only(app)["polls"] == 6, "the complete batch counts, the torn one does not"
    with open(rec, "a") as fh:
        fh.write("\n")
    assert _only(app)["polls"] == 7, "the record counts once its line is finished"


def test_a_rewritten_file_is_read_from_the_start(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    rec = tmp_path / "data/recordings/nyc.jsonl"
    generate(rec, n_aircraft=8, polls=6, start_ts=1_700_000_000.0)
    app = _app()
    assert _only(app)["polls"] == 6

    rec.unlink()
    generate(rec, n_aircraft=8, polls=3, start_ts=1_700_500_000.0)
    starts = []
    real = app_mod._iter_batches
    monkeypatch.setattr(app_mod, "_iter_batches", lambda f, start: (starts.append(start), real(f, start))[1])
    assert _only(app)["polls"] == 3
    assert starts == [0], "a file that is not an extension of what was summarised is re-read whole"


def test_the_response_carries_no_cache_internals(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    generate(tmp_path / "data/recordings/nyc.jsonl", n_aircraft=8, polls=3)
    row = _only(_app())
    assert not [k for k in row if k.startswith("_")]
    assert set(PUBLIC) <= set(row) and {"path", "sample"} <= set(row)


def test_legacy_cache_entries_survive_the_upgrade(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    rec = tmp_path / "data/recordings/nyc.jsonl"
    generate(rec, n_aircraft=8, polls=5)
    fresh = _only(_app())

    # The 1.3.0 cache keyed entries on "name:mtime_ns:size" and stored no offset.
    legacy = {k: v for k, v in fresh.items() if k in PUBLIC or k == "size_mb"}
    cache = tmp_path / "data/app/inventory.json"
    cache.write_text(json.dumps({f"nyc.jsonl:{rec.stat().st_mtime_ns}:{rec.stat().st_size}": legacy}))

    monkeypatch.setattr(app_mod, "_iter_batches", lambda f, start: (_ for _ in ()).throw(AssertionError("re-read a migrated file")))
    assert {k: _only(_app())[k] for k in PUBLIC} == {k: fresh[k] for k in PUBLIC}
    assert json.loads(cache.read_text())["nyc.jsonl"]["_offset"] == rec.stat().st_size

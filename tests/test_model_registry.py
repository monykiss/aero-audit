"""A model is a pickle; only models the registry knows are loaded."""

import json

import pytest

from aero_audit.ml import ModelIntegrityError, load_verified, verify_model
from aero_audit.ml.train import train
from aero_audit.synthetic import generate


@pytest.fixture
def trained(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec = generate(tmp_path / "synthetic.jsonl", n_aircraft=40, polls=30, seed=2)
    out = tmp_path / "models" / "kinematic_iforest.joblib"
    train([rec], out, 0.02, holdout=0.0)
    return out


def test_registered_model_loads_and_carries_identity(trained):
    info = verify_model(trained)
    assert info["exists"] and info["registered"] and info["match"] and info["entry"]["rows"] > 0
    m = load_verified(trained)
    assert m.verified_ and m.sha256_ == info["sha256"] and m.loaded_from_ == str(trained)


def test_tampered_or_unregistered_model_is_refused(trained, monkeypatch):
    monkeypatch.delenv("AERO_ALLOW_UNVERIFIED_MODEL", raising=False)
    # flip one byte: sha no longer matches the registry entry
    data = bytearray(trained.read_bytes())
    data[len(data) // 2] ^= 0xFF
    trained.write_bytes(bytes(data))
    info = verify_model(trained)
    assert info["registered"] and not info["match"]
    with pytest.raises(ModelIntegrityError, match="differ"):
        load_verified(trained)
    # no registry at all: unregistered
    (trained.parent / "registry.json").unlink()
    with pytest.raises(ModelIntegrityError, match="no entry"):
        load_verified(trained)
    # explicit override loads it but marks it unverified, and the provenance block will say so
    monkeypatch.setenv("AERO_ALLOW_UNVERIFIED_MODEL", "1")
    m = load_verified(trained)
    assert m.verified_ is False and m.sha256_ == info["sha256"]
    monkeypatch.delenv("AERO_ALLOW_UNVERIFIED_MODEL")
    assert load_verified(trained, allow_unverified=True).verified_ is False


def test_retrained_model_updates_registry_and_verifies(trained):
    reg = json.loads((trained.parent / "registry.json").read_text())
    assert len(reg) == 1 and reg[0]["sha256"] == verify_model(trained)["sha256"]
    rec = generate(trained.parent.parent / "synthetic2.jsonl", n_aircraft=30, polls=30, seed=3)
    train([rec], trained, 0.02, holdout=0.0)
    reg = json.loads((trained.parent / "registry.json").read_text())
    assert len(reg) == 2 and verify_model(trained)["match"]

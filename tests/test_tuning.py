import pytest

from aero_audit import tuning
from aero_audit.audit import rules


def test_apply_overrides_and_restores(tmp_path):
    original = rules.MAX_PLAUSIBLE_GS_KT
    cfg = tmp_path / "aero.toml"
    cfg.write_text("[rules]\nMAX_PLAUSIBLE_GS_KT = 900.0\n")
    try:
        applied = tuning.apply(cfg)
        assert applied == {"rules": {"MAX_PLAUSIBLE_GS_KT": 900.0}}
        assert rules.MAX_PLAUSIBLE_GS_KT == 900.0
        assert any(k == "MAX_PLAUSIBLE_GS_KT" and over for _, k, _, over in tuning.effective())
    finally:
        rules.MAX_PLAUSIBLE_GS_KT = original
        tuning._applied.clear()


def test_unknown_key_fails_loudly(tmp_path):
    cfg = tmp_path / "aero.toml"
    cfg.write_text("[rules]\nMAX_PLAUSIBLE_GS_KTS = 900.0\n")
    with pytest.raises(KeyError):
        tuning.apply(cfg)


def test_template_lists_tunables():
    t = tuning.template()
    assert "[rules]" in t and "# MAX_PLAUSIBLE_GS_KT" in t

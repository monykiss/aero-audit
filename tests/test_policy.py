from aero_audit.audit import policy
from aero_audit.audit.findings import SEVERITY_WEIGHT, Category, Finding, Severity
from aero_audit.audit.policy import ScoringContext, risk_score

CTX = ScoringContext(repeat_count=1, source_trust=1.0, seconds_since_first=0)


def _f(sev: Severity, cat: Category = Category.SECURITY, rule="T") -> Finding:
    return Finding(rule_id=rule, title="t", severity=sev, category=cat, ts=0)


def test_severity_is_monotonic():
    scores = [risk_score(_f(s), CTX) for s in (Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)]
    assert scores == sorted(scores) and len(set(scores)) == 5


def test_score_is_non_negative_and_finite():
    ctx = ScoringContext(repeat_count=1000, source_trust=0.0, seconds_since_first=1e9)
    s = risk_score(_f(Severity.CRITICAL), ctx)
    assert 0 <= s < float("inf")


def test_repeats_never_lower_and_compound_with_diminishing_returns():
    s1 = risk_score(_f(Severity.HIGH), ScoringContext(1, 1.0, 0))
    s2 = risk_score(_f(Severity.HIGH), ScoringContext(2, 1.0, 0))
    s4 = risk_score(_f(Severity.HIGH), ScoringContext(4, 1.0, 0))
    assert s1 < s2 < s4 and (s4 - s2) <= (s2 - s1) + 1e-9


def test_mlat_evidence_weakens_security_but_not_data_quality():
    mlat = ScoringContext(1, policy.SOURCE_TRUST["mlat"], 0)
    assert risk_score(_f(Severity.HIGH), mlat) < risk_score(_f(Severity.HIGH), CTX)
    assert risk_score(_f(Severity.HIGH, Category.DATA_QUALITY), mlat) == risk_score(_f(Severity.HIGH, Category.DATA_QUALITY), CTX)


def test_ml_is_capped_at_medium_weight():
    s = risk_score(_f(Severity.MEDIUM, Category.ML), ScoringContext(64, 1.0, 0))
    assert s <= SEVERITY_WEIGHT[Severity.MEDIUM]


def test_measured_precision_reweights_rules(monkeypatch):
    monkeypatch.setitem(policy.RULE_PRECISION, "LOWPREC", 0.0)
    monkeypatch.setitem(policy.RULE_PRECISION, "HIPREC", 1.0)
    lo = risk_score(_f(Severity.HIGH, rule="LOWPREC"), CTX)
    hi = risk_score(_f(Severity.HIGH, rule="HIPREC"), CTX)
    assert lo == hi * policy.PRECISION_FLOOR

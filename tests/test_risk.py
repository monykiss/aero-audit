from aero_audit.risk import RISK_REGISTER, assess, rating, score
from aero_audit.risk.register import observed_likelihood
from aero_audit.security import THREATS


def test_rating_bands():
    assert rating(score(5, 5)) == "critical" and rating(score(2, 5)) == "high"
    assert rating(score(2, 3)) == "medium" and rating(score(1, 2)) == "low"


def test_register_references_real_threats_and_rules():
    from aero_audit.audit.rules import RULE_CATALOG

    tids = {t.id for t in THREATS}
    for r in RISK_REGISTER:
        assert set(r.threat_ids) <= tids, r.id
        assert set(r.evidence_rules) <= set(RULE_CATALOG), r.id


def test_observed_likelihood_is_bounded():
    assert observed_likelihood(2, 0) == 1  # large sample, nothing seen -> one band down
    assert observed_likelihood(2, 0, aircraft=50) == 2  # small sample: silence proves nothing
    assert observed_likelihood(2, 5) == 2
    assert observed_likelihood(2, 20) == 3
    assert observed_likelihood(4, 500) == 5


def test_assess_moves_likelihood_with_evidence():
    quiet = {r["id"]: r for r in assess({"unique_aircraft": 1000, "by_rule": {}})}
    noisy = {r["id"]: r for r in assess({"unique_aircraft": 1000, "by_rule": {"SEC-010": 100}})}
    assert noisy["R01"]["L"] > quiet["R01"]["L"]
    assert noisy["R01"]["rating"] in ("high", "critical")


def test_merge_summaries_sums_rules_and_aircraft():
    from aero_audit.risk import merge_summaries

    m = merge_summaries([{"by_rule": {"SEC-012": 2}, "unique_aircraft": 10, "findings_total": 2, "batches": 3},
                         {"by_rule": {"SEC-012": 1, "OPS-002": 4}, "unique_aircraft": 5, "findings_total": 5, "batches": 2}])
    assert m == {"by_rule": {"SEC-012": 3, "OPS-002": 4}, "unique_aircraft": 15, "findings_total": 7, "batches": 5, "recordings": 2}


def test_stale_contact_does_not_drive_jamming_risk():
    from aero_audit.risk import RISK_REGISTER

    r03 = next(r for r in RISK_REGISTER if r.id == "R03")
    assert "OPS-001" not in r03.evidence_rules


def test_wilson_lower_bound_behaves():
    from aero_audit.risk.register import wilson_lower

    assert wilson_lower(0, 100) == 0.0
    assert 0.39 < wilson_lower(50, 100) < 0.41
    assert wilson_lower(1, 10) < 0.1  # one hit in ten is not evidence of a 10% rate


def test_residual_never_exceeds_inherent_and_precision_weights_evidence():
    from aero_audit.risk import RISK_REGISTER, assess

    for r in RISK_REGISTER:
        assert 1 <= r.residual <= r.inherent
    summary = {"unique_aircraft": 1000, "by_rule": {"SEC-010": 100}}
    full = {x["id"]: x for x in assess(summary, rule_precision={"SEC-010": 1.0})}
    weak = {x["id"]: x for x in assess(summary, rule_precision={"SEC-010": 0.1})}
    assert weak["R01"]["expected_true"] < full["R01"]["expected_true"]
    assert weak["R01"]["L"] <= full["R01"]["L"]
    assert {"residual", "residual_rating", "control_effectiveness", "rate_lb_per_1000"} <= set(full["R01"])


def test_optional_configuration_rules_are_not_register_evidence():
    from aero_audit.risk import RISK_REGISTER

    for r in RISK_REGISTER:
        assert "SEC-020" not in r.evidence_rules, r.id
    r07 = next(r for r in RISK_REGISTER if r.id == "R07")
    assert r07.evidence_rules == ()

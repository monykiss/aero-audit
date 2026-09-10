"""Posture: the bird's-eye view. One JSON document (and a Markdown rendering) that says, per
domain and per pillar, what is implemented, what evidence exists on disk right now, where the
residual risk sits, which studies can run, and one index that only moves when those move.

``static=True`` omits anything time-dependent (file ages, chain state) so the generated document
in docs/ is deterministic and CI can check it for drift.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .controls import CONTROLS, PILLARS, POLICIES, coverage, evidence_present, implementation_index
from .domains import DOMAINS
from .register import by_rating, unified_register
from .studies import STUDIES, latest_results


def _freshness() -> dict[str, Any]:
    from ..ml import verify_model
    from ..web.audit import AUDIT_FILE, verify_file

    now = time.time()
    reports = sorted(Path("reports").glob("*.manifest.json"), key=lambda p: p.stat().st_mtime) if Path("reports").is_dir() else []
    ev = Path("models/evaluation.json")
    model = Path("models/kinematic_iforest.joblib")
    chain = verify_file(AUDIT_FILE) if AUDIT_FILE.is_file() else None
    vm = verify_model(model) if model.is_file() else None
    return {
        "latest_report_age_h": round((now - reports[-1].stat().st_mtime) / 3600, 1) if reports else None,
        "reports_with_manifest": len(reports),
        "evaluation_age_days": round((now - ev.stat().st_mtime) / 86400, 1) if ev.is_file() else None,
        "model_verified": bool(vm and vm["match"]) if vm else None,
        "audit_chain_ok": chain["ok"] if chain else None,
        "audit_entries": chain["entries"] if chain else 0,
        "nasa_catalog_present": Path("data/space/nasa3d_catalog.json").is_file(),
        "study_results": len(latest_results()),
    }


def posture(summary: dict[str, Any] | None = None, static: bool = False) -> dict[str, Any]:
    cov = coverage()
    risks = unified_register(summary)
    idx = implementation_index()
    evidence = {cid: evidence_present(c) for cid, c in CONTROLS.items()} if not static else {}
    missing = sorted({e for items in evidence.values() for e, ok in items.items() if not ok})
    runnable = sum(1 for s in STUDIES.values() if s.status == "runnable")
    fresh = None if static else _freshness()
    res = by_rating(risks)
    risk_share_ok = round(sum(v for k, v in res.items() if k in ("low", "medium")) / max(len(risks), 1), 3)
    fresh_score = 0.0
    if fresh:
        fresh_score = sum([
            0.4 if fresh["audit_chain_ok"] else 0.0,
            0.3 if fresh["model_verified"] else 0.0,
            0.3 if (fresh["latest_report_age_h"] is not None and fresh["latest_report_age_h"] <= 24 * 7) else 0.0,
        ])
    index = round(0.4 * idx + 0.2 * (cov["standards_with_controls"] / cov["standards_total"]) + 0.2 * risk_share_ok
                  + 0.1 * (runnable / max(len(STUDIES), 1)) + (0.1 * fresh_score if fresh else 0.1 * idx), 3)
    return {
        "generated_at": None if static else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "governance_index": index,
        "components": {"controls_implementation": idx, "standards_coverage": round(cov["standards_with_controls"] / cov["standards_total"], 3),
                       "risk_share_low_or_medium": risk_share_ok, "studies_runnable_share": round(runnable / max(len(STUDIES), 1), 3),
                       "evidence_freshness": None if static else round(fresh_score, 2)},
        "domains": [{**d.to_dict(), "controls": cov["by_domain"][d.key], "rules": _rule_count(d.rule_prefixes)} for d in DOMAINS.values()],
        "pillars": {p: {"controls": cov["by_pillar"][p], "ids": [c.id for c in CONTROLS.values() if c.pillar == p]} for p in PILLARS},
        "controls": [{**c.to_dict(), "evidence_missing": [e for e, ok in evidence.get(c.id, {}).items() if not ok]} for c in CONTROLS.values()],
        "standards": cov["by_standard"],
        "risks": {"rows": risks, "by_inherent": by_rating(risks, "rating"), "by_residual": res,
                  "top_residual": [{"id": r["id"], "domain": r["domain"], "title": r["title"], "residual": r["residual"], "rating": r["residual_rating"]} for r in risks[:6]]},
        "studies": {"rows": [s.to_dict() for s in STUDIES.values()], "runnable": runnable, "latest": {} if static else latest_results()},
        "policies": [p.to_dict() for p in POLICIES],
        "evidence": {"missing": missing},
        "freshness": fresh,
        "evidence_basis": "live session" if summary else "baseline (no session evidence)",
    }


def _rule_count(prefixes: tuple[str, ...]) -> int:
    from ..audit.rules import RULE_CATALOG
    from .controls import SPACE_RULES

    ids = list(RULE_CATALOG) + list(SPACE_RULES)
    return sum(1 for r in ids for p in prefixes if r.startswith(p + "-"))


def render_markdown(p: dict[str, Any], title: str = "Governance posture") -> str:
    c = p["components"]
    lines = [f"# {title}", "", f"Governance index: **{p['governance_index']:.0%}** "
             f"(controls {c['controls_implementation']:.0%}, standards {c['standards_coverage']:.0%}, risk share low/medium {c['risk_share_low_or_medium']:.0%}, "
             f"studies runnable {c['studies_runnable_share']:.0%}" + (f", evidence freshness {c['evidence_freshness']:.0%}" if c["evidence_freshness"] is not None else "") + f"). Basis: {p['evidence_basis']}.", "",
             "## Domains", "", "| Domain | Status | Rules | Controls implemented / partial / planned | Data sources |", "|---|---|---|---|---|"]
    for d in p["domains"]:
        k = d["controls"]
        lines.append(f"| {d['name']} | {d['status']} | {d['rules']} | {k['implemented']} / {k['partial']} / {k['planned']} | {'; '.join(d['data_sources'])} |")
    lines += ["", "## Pillars", "", "| Pillar | Implemented | Partial | Planned |", "|---|---|---|---|"]
    for name, v in p["pillars"].items():
        k = v["controls"]
        lines.append(f"| {name} | {k['implemented']} | {k['partial']} | {k['planned']} |")
    lines += ["", "## Risk (residual, all domains)", "", "| Id | Domain | Risk | Inherent | Residual |", "|---|---|---|---|---|"]
    for r in p["risks"]["rows"]:
        lines.append(f"| {r['id']} | {r['domain']} | {r['title']} | {r['score']} {r['rating']} | {r['residual']} {r['residual_rating']} |")
    lines += ["", f"By residual rating: {p['risks']['by_residual']}", "", "## Studies", "", "| Id | Study | Domain | Status |", "|---|---|---|---|"]
    for s in p["studies"]["rows"]:
        lines.append(f"| {s['id']} | {s['title']} | {s['domain']} | {s['status']} |")
    if p.get("freshness"):
        f = p["freshness"]
        lines += ["", "## Evidence on disk", "", f"- Latest report with manifest: {f['latest_report_age_h']} h ago ({f['reports_with_manifest']} on disk)",
                  f"- Evaluation file age: {f['evaluation_age_days']} days", f"- Model verified against registry: {f['model_verified']}",
                  f"- Audit chain: {'verified' if f['audit_chain_ok'] else 'broken or absent'} ({f['audit_entries']} entries)",
                  f"- NASA catalogue present: {f['nasa_catalog_present']}; study results on disk: {f['study_results']}"]
    if p["evidence"]["missing"]:
        lines += ["", "## Evidence claimed but not on disk", ""] + [f"- {e}" for e in p["evidence"]["missing"]]
    return "\n".join(lines) + "\n"


__all__ = ["posture", "render_markdown"]

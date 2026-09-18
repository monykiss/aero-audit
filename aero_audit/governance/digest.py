"""The periodic digest: every report of the last N days folded into one brief with a manifest.

Analyses write one report each; an operator reads one page a week. The digest groups reports by
kind, counts findings by rule and severity, lists the worst ones, adds the posture index, the
latest live check, the scheduled-intake state if the app persisted it, the classifier hold-out
number, and the open decisions from the release plan. It is itself a report (JSON, Markdown,
manifest), so it can be bundled or attached, and it runs as a scheduled job.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..audit.findings import SEVERITY_ORDER

REPORTS = Path("reports")
KIND_RX = re.compile(r"^(conjunctions|cdm|debris|space_weather|launches|maneuvers|satcat|wellclear|uas_risk|uas_trend|encounter_model|utm_check|classify_eval|live_check|risk_assessment|evaluation|bench|bench_space|corroborate|demo_session|digest|.+?_telemetry)")


def _kind(stem: str) -> str:
    m = KIND_RX.match(stem)
    k = m.group(1) if m else stem.split("_")[0]
    return "telemetry" if k.endswith("_telemetry") else k


def collect(days: float = 7.0, reports_dir: str | Path = REPORTS, now: float | None = None) -> list[dict[str, Any]]:
    ts_now = time.time() if now is None else now
    cutoff = ts_now - days * 86400
    rows = []
    for p in sorted(Path(reports_dir).glob("*.json")):
        if p.name.endswith(".manifest.json") or p.stem.startswith("digest_"):
            continue
        st = p.stat()
        if st.st_mtime < cutoff:
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):  # a few reports are bare lists (registry-style dumps); they carry no findings
            d = {}
        findings = d.get("findings") or []
        rows.append({"file": p.name, "kind": _kind(p.stem), "mtime": st.st_mtime, "findings": [{"rule_id": f.get("rule_id"), "severity": f.get("severity"), "title": f.get("title"), "callsign": f.get("callsign")} for f in findings if isinstance(f, dict)],
                     "manifest": (p.parent / f"{p.stem}.manifest.json").is_file(), "degraded": bool((d.get("summary") or {}).get("degraded")) if isinstance(d.get("summary"), dict) else False})
    return rows


def build(days: float = 7.0, reports_dir: str | Path = REPORTS, now: float | None = None) -> dict[str, Any]:
    rows = collect(days, reports_dir, now)
    by_kind: dict[str, dict[str, Any]] = defaultdict(lambda: {"reports": 0, "findings": 0, "with_manifest": 0, "degraded": 0})
    sev = Counter()
    rules = Counter()
    worst: list[dict[str, Any]] = []
    for r in rows:
        k = by_kind[r["kind"]]
        k["reports"] += 1
        k["findings"] += len(r["findings"])
        k["with_manifest"] += int(r["manifest"])
        k["degraded"] += int(r["degraded"])
        for f in r["findings"]:
            sev[f["severity"] or "?"] += 1
            rules[f["rule_id"] or "?"] += 1
            worst.append({**f, "report": r["file"]})
    order = list(SEVERITY_ORDER) if not isinstance(SEVERITY_ORDER, dict) else sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get)
    worst.sort(key=lambda f: (order.index(f["severity"]) if f.get("severity") in order else 99, f.get("rule_id") or ""))
    out: dict[str, Any] = {"days": days, "reports": len(rows), "by_kind": dict(sorted(by_kind.items())), "findings_by_severity": dict(sev), "findings_by_rule": dict(rules.most_common(15)),
                           "worst": worst[:20], "reports_without_manifest": [r["file"] for r in rows if not r["manifest"]], "degraded_reports": [r["file"] for r in rows if r["degraded"]]}
    # context that is not a report: posture, hold-out, live check, scheduler, decisions
    try:
        from .posture import posture

        p = posture(None, static=True)
        out["posture"] = {"governance_index": p["governance_index"], **{k: v for k, v in p["components"].items()}}
    except Exception as e:  # noqa: BLE001 - the digest must render even when a component is unavailable
        out["posture"] = {"error": f"{type(e).__name__}: {e}"}
    live = [r for r in rows if r["kind"] == "live_check"]
    out["live_check"] = None
    if live:
        try:
            d = json.loads((Path(reports_dir) / live[-1]["file"]).read_text())["summary"]
            out["live_check"] = {"file": live[-1]["file"], "passed": d.get("passed"), "total": d.get("total"), "spacetrack_used": d.get("spacetrack_used")}
        except (OSError, ValueError, KeyError):
            out["live_check"] = {"file": live[-1]["file"], "error": "unreadable"}  # optional context; the digest still renders
    ev = [r for r in rows if r["kind"] == "classify_eval"]
    out["classifier_holdout"] = None
    if ev:
        try:
            d = json.loads((Path(reports_dir) / ev[-1]["file"]).read_text())["summary"]
            out["classifier_holdout"] = {m["model"]: m["accuracy"] for m in d.get("models", [])}
        except (OSError, ValueError, KeyError):
            out["classifier_holdout"] = None  # optional context; an unreadable evaluation report is simply not shown
    jobs = Path("data/app/jobs.json")
    out["jobs"] = None
    if jobs.is_file():
        try:
            js = json.loads(jobs.read_text())
            recent = [j for j in (js if isinstance(js, list) else js.get("jobs", [])) if (j.get("finished") or 0) >= (time.time() if now is None else now) - days * 86400]
            out["jobs"] = {"finished": len(recent), "failed": sum(1 for j in recent if j.get("status") == "failed"), "by_type": dict(Counter(j.get("type") for j in recent))}
        except (OSError, ValueError, AttributeError):
            out["jobs"] = {"error": "jobs.json unreadable"}  # the digest still renders; the job history is optional context
    try:
        from .publish import checks, summary

        s = summary(checks("."))
        out["publish"] = {"passed": s["passed"], "total": s["total"], "open": s["failed"]}
    except Exception as e:  # noqa: BLE001
        out["publish"] = {"error": f"{type(e).__name__}: {e}"}
    out["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)) if now else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return out


def render_markdown(d: dict[str, Any]) -> str:
    lines = [f"# Digest: last {d['days']:g} days ({d['generated_at']})", "",
             f"{d['reports']} reports; findings by severity {d['findings_by_severity'] or 'none'}.", ""]
    p = d.get("posture") or {}
    if "governance_index" in p:
        lines.append(f"Governance index **{p['governance_index']:.0%}** (controls {p.get('controls_implementation', 0):.0%}, standards {p.get('standards_coverage', 0):.0%}).")
    if d.get("live_check"):
        lc = d["live_check"]
        lines.append(f"Live check: {lc['passed']}/{lc['total']} keyless paths ({lc['file']}); Space-Track used: {lc['spacetrack_used']}.")
    if d.get("classifier_holdout"):
        lines.append("Classifier hold-out: " + ", ".join(f"{k} {v:.1%}" for k, v in d["classifier_holdout"].items()) + ".")
    if d.get("jobs"):
        j = d["jobs"]
        lines.append(f"Jobs: {j['finished']} finished, {j['failed']} failed ({j['by_type']}).")
    pub = d.get("publish") or {}
    if "passed" in pub:
        lines.append(f"Publication gate: {pub['passed']}/{pub['total']}; open: {', '.join(pub['open']) or 'none'}.")
    lines += ["", "## Reports by kind", "", "| Kind | Reports | Findings | With manifest | Degraded |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {v['reports']} | {v['findings']} | {v['with_manifest']} | {v['degraded']} |" for k, v in d["by_kind"].items()]
    lines += ["", "## Findings by rule", "", "| Rule | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in d["findings_by_rule"].items()]
    lines += ["", "## Worst findings", "", "| Severity | Rule | Object | Finding | Report |", "|---|---|---|---|---|"]
    lines += [f"| {f.get('severity')} | {f.get('rule_id')} | {f.get('callsign') or ''} | {str(f.get('title') or '').replace('|', '/')[:90]} | {f['report']} |" for f in d["worst"]]
    if d["reports_without_manifest"]:
        lines += ["", "## Reports without a manifest", ""] + [f"- {x}" for x in d["reports_without_manifest"]]
    if d["degraded_reports"]:
        lines += ["", "## Reports produced from cached products (fetch failed)", ""] + [f"- {x}" for x in d["degraded_reports"]]
    return "\n".join(lines) + "\n"


def write(days: float = 7.0, out_dir: str | Path = REPORTS, now: float | None = None) -> dict[str, Path]:
    from ..audit.generic_report import write_generic

    d = build(days, out_dir, now)
    paths = write_generic(out_dir, "digest", "summary", d, [], title=f"aero-audit digest: last {days:g} days")
    paths["md"].write_text(render_markdown(d))  # the digest's own Markdown replaces the generic rendering
    from .. import provenance as prov

    paths["manifest"].write_text(json.dumps(prov.manifest({"json": paths["json"], "md": paths["md"]}, json.loads(paths["json"].read_text())["provenance"]), indent=2, default=str))
    return paths


__all__ = ["build", "collect", "render_markdown", "write"]

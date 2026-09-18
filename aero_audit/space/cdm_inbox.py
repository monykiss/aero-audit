"""CDM intake: a folder of messages (KVN or CCSDS XML) becomes a de-duplicated ledger and a set
of conjunction events, each event being the series of messages about the same pair around the
same time of closest approach, with the probability of collision tracked from message to message.

The ledger is append-only JSONL keyed by message id and content hash. Events answer the operator's
questions: is Pc rising or falling, how old is the latest message, and what does the latest one
recommend. Also handles the summary rows the Space-Track ``cdm_public`` class returns (no
covariance: recorded with the stated Pc, never recomputed).
"""

from __future__ import annotations

import hashlib
import json
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cdm import CDM, CdmObject, assess, parse_cdm

INBOX = Path("data/space/cdm/inbox")
LEDGER = Path("data/space/cdm/ledger.jsonl")
TCA_WINDOW_S = 600.0
# Space-Track's user agreement (10 USC 2274(c)(2)): data and analyses of it are not transferred to another entity without
# prior approval. Rows carrying this marker stay out of evidence bundles and public artefacts (evidence.collect, PUB-11).
RESTRICTED_SPACETRACK = "space-track user agreement: no redistribution without prior approval (10 USC 2274)"


def parse_cdm_xml(text: str) -> CDM:
    """CCSDS NDM/XML form: header, relativeMetadataData, and two segment/metadata+data blocks."""
    root = ET.fromstring(text)

    def strip(tag: str) -> str:
        return tag.split("}", 1)[-1]

    def texts(node: ET.Element) -> dict[str, str]:
        out: dict[str, str] = {}
        for el in node.iter():
            if len(el) == 0 and el.text and el.text.strip():
                out[strip(el.tag).upper()] = el.text.strip()
        return out

    cdm = CDM()
    segments = [el for el in root.iter() if strip(el.tag) == "segment"]
    head: dict[str, str] = {}
    for el in root.iter():
        name = strip(el.tag)
        if name in ("header", "relativeMetadataData"):
            head.update(texts(el))
    cdm.header = head
    cdm.message_id = head.get("MESSAGE_ID", "")
    cdm.originator = head.get("ORIGINATOR", "")
    cdm.creation_date = head.get("CREATION_DATE", "")
    cdm.tca = head.get("TCA", "")
    for key, attr in (("MISS_DISTANCE", "miss_distance_m"), ("RELATIVE_SPEED", "relative_speed_ms"), ("COLLISION_PROBABILITY", "stated_pc")):
        if key in head:
            try:
                setattr(cdm, attr, float(head[key].split()[0]))
            except ValueError:
                pass  # an unparseable numeric field stays None; the message is still recorded and ORB-005 reports inconsistency
    for seg in segments:
        f = texts(seg)
        o = CdmObject(designator=f.get("OBJECT_DESIGNATOR", ""), name=f.get("OBJECT_NAME", ""), ref_frame=f.get("REF_FRAME", ""), fields=f)
        if all(k in f for k in ("X", "Y", "Z")):
            o.position_km = tuple(float(f[k].split()[0]) for k in ("X", "Y", "Z"))  # type: ignore[assignment]
        if all(k in f for k in ("X_DOT", "Y_DOT", "Z_DOT")):
            o.velocity_kms = tuple(float(f[k].split()[0]) for k in ("X_DOT", "Y_DOT", "Z_DOT"))  # type: ignore[assignment]
        if all(k in f for k in ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N")):
            crr, ctr, ctt, cnr, cnt, cnn = (float(f[k].split()[0]) for k in ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N"))
            o.cov_rtn_m2 = [[crr, ctr, cnr], [ctr, ctt, cnt], [cnr, cnt, cnn]]
        cdm.objects.append(o)
    return cdm


def load_any(path: str | Path) -> CDM:
    text = Path(path).read_text(errors="replace")
    return parse_cdm_xml(text) if text.lstrip().startswith("<") else parse_cdm(text)


def _pair_key(cdm: CDM) -> str:
    ids = sorted(o.designator or o.name or "?" for o in cdm.objects[:2])
    return ":".join(ids)


def _tca_ts(tca: str) -> float | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%jT%H:%M:%S.%f"):
        try:
            return datetime.strptime(tca[:26], fmt).replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
    return None


def _ledger_rows(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return []


def process_inbox(inbox: str | Path = INBOX, ledger: str | Path = LEDGER, hbr_m: float = 20.0) -> dict[str, Any]:
    """Assess every new message in the inbox, append to the ledger, return what happened."""
    inbox, ledger = Path(inbox), Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    known = {(r.get("message_id"), r.get("sha256")) for r in _ledger_rows(ledger)}
    processed, skipped, errors = [], 0, []
    for p in sorted(inbox.glob("*")):
        if p.suffix.lower() not in (".cdm", ".kvn", ".xml", ".txt"):
            continue
        data = p.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        try:
            cdm = load_any(p)
        except (ET.ParseError, ValueError) as e:
            errors.append({"file": p.name, "error": f"{type(e).__name__}: {e}"})
            continue
        if (cdm.message_id, sha) in known:
            skipped += 1
            continue
        res, fs = assess(cdm, hbr_m)
        pc = (res.get("pc") or {}).get("pc")
        row = {"received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "file": p.name, "sha256": sha, "message_id": cdm.message_id,
               "originator": cdm.originator, "creation_date": cdm.creation_date, "tca": cdm.tca, "tca_ts": _tca_ts(cdm.tca), "pair": _pair_key(cdm),
               "objects": [o.designator or o.name for o in cdm.objects], "pc": pc, "stated_pc": cdm.stated_pc, "miss_m": (res.get("pc") or {}).get("miss_m"),
               "stated_miss_m": cdm.miss_distance_m, "error": res.get("error"), "findings": [{"rule": f.rule_id, "severity": f.severity.value, "title": f.title} for f in fs]}
        with open(ledger, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        known.add((cdm.message_id, sha))
        processed.append(row)
    return {"inbox": str(inbox), "ledger": str(ledger), "processed": processed, "skipped_duplicates": skipped, "errors": errors}


def record_summary(rows: list[dict[str, Any]], ledger: str | Path = LEDGER, source: str = "space-track cdm_public") -> int:
    """Store summary conjunctions (e.g. Space-Track cdm_public rows: SAT_1_ID, SAT_2_ID, TCA, MIN_RNG, PC) without covariance."""
    ledger = Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    known = {(r.get("message_id"), r.get("sha256")) for r in _ledger_rows(ledger)}
    n = 0
    with open(ledger, "a") as fh:
        for r in rows:
            mid = str(r.get("CDM_ID") or r.get("MESSAGE_ID") or f"{r.get('SAT_1_ID')}-{r.get('SAT_2_ID')}-{r.get('TCA')}")
            sha = hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
            if (mid, sha) in known:
                continue
            pc = r.get("PC")
            miss = r.get("MIN_RNG")
            row = {"received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "file": source, "sha256": sha, "message_id": mid,
                   "originator": r.get("EMERGENCY_REPORTABLE", "") and "18 SDS" or "space-track", "creation_date": r.get("CREATED", ""), "tca": str(r.get("TCA", "")),
                   "tca_ts": _tca_ts(str(r.get("TCA", ""))), "pair": ":".join(sorted(str(x) for x in (r.get("SAT_1_ID"), r.get("SAT_2_ID")))),
                   "objects": [str(r.get("SAT_1_ID")), str(r.get("SAT_2_ID"))], "pc": None, "stated_pc": float(pc) if pc not in (None, "") else None,
                   "miss_m": None, "stated_miss_m": float(miss) * 1000.0 if miss not in (None, "") else None, "error": None, "findings": [], "summary_only": True,
                   "restricted": RESTRICTED_SPACETRACK}
            fh.write(json.dumps(row, default=str) + "\n")
            known.add((mid, sha))
            n += 1
    return n


def restricted_share(ledger: str | Path = LEDGER) -> dict[str, Any]:
    """How much of the ledger is Space-Track material (restricted) versus files supplied to the inbox."""
    rows = _ledger_rows(Path(ledger)) if Path(ledger).is_file() else []
    r = sum(1 for x in rows if x.get("restricted"))
    return {"rows": len(rows), "restricted": r, "note": RESTRICTED_SPACETRACK if r else None}


def events(ledger: str | Path = LEDGER, now: float | None = None) -> list[dict[str, Any]]:
    """Group ledger rows into conjunction events (same pair, TCA within a window) and describe the Pc trend."""
    now = time.time() if now is None else now
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in _ledger_rows(ledger):
        tca = r.get("tca_ts")
        bucket = int(tca // TCA_WINDOW_S) if tca else -1
        groups[(r["pair"], bucket)].append(r)
    out = []
    for (pair, _), rows in groups.items():
        rows.sort(key=lambda r: (r.get("creation_date") or "", r.get("received_at") or ""))
        pcs = [r["pc"] if r.get("pc") is not None else r.get("stated_pc") for r in rows]
        pcs = [p for p in pcs if p is not None]
        trend = "stable"
        if len(pcs) >= 2:
            trend = "escalating" if pcs[-1] > pcs[-2] * 1.5 else ("de-escalating" if pcs[-1] < pcs[-2] / 1.5 else "stable")
        latest = rows[-1]
        tca_ts = latest.get("tca_ts")
        out.append({"pair": pair, "objects": latest.get("objects"), "tca": latest.get("tca"), "hours_to_tca": round((tca_ts - now) / 3600, 1) if tca_ts else None,
                    "messages": len(rows), "latest_pc": pcs[-1] if pcs else None, "max_pc": max(pcs) if pcs else None, "trend": trend,
                    "latest_message_id": latest.get("message_id"), "latest_creation": latest.get("creation_date"),
                    "latest_findings": latest.get("findings", []), "summary_only": all(r.get("summary_only") for r in rows)})
    out.sort(key=lambda e: -(e["latest_pc"] or 0))
    return out


__all__ = ["INBOX", "LEDGER", "TCA_WINDOW_S", "events", "load_any", "parse_cdm_xml", "process_inbox", "record_summary"]

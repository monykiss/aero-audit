"""Alert sinks: get high-severity findings out of the terminal and into a channel someone watches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import httpx

from .audit.findings import SEVERITY_ORDER, Finding, Severity
from .security.playbooks import playbook_for


class AlertSink(Protocol):
    def send(self, finding: Finding) -> None:
        """Deliver one finding."""


class JsonlSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, finding: Finding) -> None:
        with open(self.path, "a") as fh:
            fh.write(finding.model_dump_json() + "\n")


class WebhookSink:
    """POSTs a compact JSON payload (works with Slack/Teams incoming webhooks via a 'text' field)."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, finding: Finding) -> None:
        pb = playbook_for(finding.rule_id)
        text = (
            f"[{finding.severity.value.upper()}] {finding.rule_id} {finding.title} "
            f"aircraft={finding.icao24} {finding.callsign or ''} risk={finding.risk_score:.1f}"
            + (f" | first step: {pb.triage[0]}" if pb else "")
        )
        payload = {"text": text, "finding": json.loads(finding.model_dump_json())}
        try:
            httpx.post(self.url, json=payload, timeout=self.timeout).raise_for_status()
        except httpx.HTTPError as e:
            print(f"[alerts] webhook failed: {type(e).__name__}: {e}")


class Alerter:
    def __init__(self, sinks: list[AlertSink], min_severity: Severity = Severity.HIGH) -> None:
        self.sinks = sinks
        self.min_severity = min_severity
        self.sent = 0

    def _eligible(self, f: Finding) -> bool:
        return SEVERITY_ORDER.index(f.severity) <= SEVERITY_ORDER.index(self.min_severity)

    def dispatch(self, findings: list[Finding]) -> int:
        n = 0
        for f in findings:
            if self._eligible(f):
                for s in self.sinks:
                    s.send(f)
                n += 1
        self.sent += n
        return n

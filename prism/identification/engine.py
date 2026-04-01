"""AI Traffic Identification Engine — three-layer matching with weighted scoring."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import yaml


SIGNATURES_DIR = Path(__file__).parent.parent / "signatures"

# Layer weights
WEIGHT_DOMAIN = 0.40
WEIGHT_URI_HEADER = 0.35
WEIGHT_PAYLOAD = 0.25

# Minimum confidence to be considered AI traffic
MIN_CONFIDENCE = 0.40


@dataclass
class MatchResult:
    is_ai: bool
    provider: str
    service_type: str
    confidence: float
    matched_pattern: Optional[str] = None


@dataclass
class DomainEntry:
    provider_key: str
    display_name: str
    patterns: list[str]
    confidence: float


@dataclass
class PatternEntry:
    name: str
    provider: str
    service_type: str
    uri_regex: Optional[str]
    headers: dict[str, str]
    body_contains: list[str]
    confidence: float
    _compiled_uri: Optional[re.Pattern] = field(default=None, repr=False, compare=False)
    _compiled_headers: dict[str, re.Pattern] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self):
        if self.uri_regex:
            self._compiled_uri = re.compile(self.uri_regex, re.IGNORECASE)
        for k, v in self.headers.items():
            self._compiled_headers[k.lower()] = re.compile(v, re.IGNORECASE)


class SignatureDB:
    """Loads and manages AI traffic signatures. Supports hot-reload via reload()."""

    def __init__(self):
        self._domains: list[DomainEntry] = []
        self._patterns: list[PatternEntry] = []
        self._provider_names: dict[str, str] = {}
        self.load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self):
        self._load_domains()
        self._load_patterns()

    def _load_domains(self):
        path = SIGNATURES_DIR / "ai_domains.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        entries = []
        names = {}
        for key, info in data.get("providers", {}).items():
            entry = DomainEntry(
                provider_key=key,
                display_name=info.get("display_name", key),
                patterns=info.get("domains", []),
                confidence=float(info.get("confidence", 1.0)),
            )
            entries.append(entry)
            names[key] = entry.display_name
        self._domains = entries
        self._provider_names = names

    def _load_patterns(self):
        path = SIGNATURES_DIR / "ai_patterns.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        entries = []
        for p in data.get("patterns", []):
            entry = PatternEntry(
                name=p.get("name", ""),
                provider=p.get("provider", "unknown"),
                service_type=p.get("service_type", "chat"),
                uri_regex=p.get("uri_regex"),
                headers=p.get("headers", {}),
                body_contains=p.get("body_contains", []),
                confidence=float(p.get("confidence", 0.5)),
            )
            entries.append(entry)
        self._patterns = entries

    def reload(self):
        self.load()

    def provider_display_name(self, key: str) -> str:
        return self._provider_names.get(key, key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def identify(
        self,
        host: str,
        path: str,
        headers: dict[str, str],
        body: Optional[bytes] = None,
    ) -> MatchResult:
        """
        Run three-layer identification and return a MatchResult.
        """
        norm_headers = {k.lower(): v for k, v in headers.items()}

        # Layer 1 — Domain
        domain_score, domain_provider = self._match_domain(host)

        # Layer 2 — URI + Headers
        uri_score, uri_provider, uri_service, uri_pattern = self._match_uri_headers(
            path, norm_headers
        )

        # Layer 3 — Payload
        payload_score, payload_service = self._match_payload(body, norm_headers)

        # Weighted combination
        total = (
            domain_score * WEIGHT_DOMAIN
            + uri_score * WEIGHT_URI_HEADER
            + payload_score * WEIGHT_PAYLOAD
        )

        # Determine provider and service type (priority: uri > domain > payload)
        provider = uri_provider or domain_provider or "unknown"
        service_type = uri_service or payload_service or "chat"

        is_ai = total >= MIN_CONFIDENCE
        return MatchResult(
            is_ai=is_ai,
            provider=provider,
            service_type=service_type,
            confidence=round(total, 3),
            matched_pattern=uri_pattern,
        )

    def is_ai_host(self, host: str) -> bool:
        score, _ = self._match_domain(host)
        return score >= 0.5

    # ------------------------------------------------------------------
    # Layer implementations
    # ------------------------------------------------------------------

    def _match_domain(self, host: str) -> tuple[float, Optional[str]]:
        host_lower = host.lower()
        for entry in self._domains:
            for pattern in entry.patterns:
                if fnmatch.fnmatch(host_lower, pattern.lower()):
                    return entry.confidence, entry.provider_key
        return 0.0, None

    def _match_uri_headers(
        self, path: str, norm_headers: dict[str, str]
    ) -> tuple[float, Optional[str], Optional[str], Optional[str]]:
        best_score = 0.0
        best_provider = None
        best_service = None
        best_name = None

        for pat in self._patterns:
            score = 0.0
            uri_matched = False
            headers_matched = True

            # URI match
            if pat._compiled_uri and pat._compiled_uri.search(path):
                score += pat.confidence * 0.7
                uri_matched = True
            elif pat._compiled_uri:
                continue  # URI pattern defined but not matched — skip

            # Header match (all defined headers must match for bonus)
            if pat._compiled_headers:
                matched_hdrs = 0
                for k, compiled in pat._compiled_headers.items():
                    val = norm_headers.get(k, "")
                    if compiled.search(val):
                        matched_hdrs += 1
                if matched_hdrs == len(pat._compiled_headers):
                    score += pat.confidence * 0.3
                elif uri_matched and matched_hdrs > 0:
                    score += pat.confidence * 0.15  # partial header bonus

            if score > best_score:
                best_score = score
                best_provider = pat.provider if pat.provider != "unknown" else None
                best_service = pat.service_type
                best_name = pat.name

        return min(best_score, 1.0), best_provider, best_service, best_name

    def _match_payload(
        self, body: Optional[bytes], norm_headers: dict[str, str]
    ) -> tuple[float, Optional[str]]:
        if not body:
            return 0.0, None

        content_type = norm_headers.get("content-type", "")
        if "json" not in content_type and "form" not in content_type:
            # Still try for multipart (file uploads)
            if "multipart" not in content_type:
                return 0.0, None

        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            return 0.0, None

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}

        score = 0.0
        service = None

        # Classic LLM chat payload
        if "model" in payload and "messages" in payload:
            score = 0.9
            service = "chat"
        elif "model" in payload and "prompt" in payload:
            score = 0.85
            service = "completion"
        elif "model" in payload and "input" in payload:
            score = 0.75
            service = "embedding"
        elif "messages" in payload and isinstance(payload.get("messages"), list):
            score = 0.65
            service = "chat"
        elif "prompt" in payload and "max_tokens" in payload:
            score = 0.65
            service = "completion"

        # Body contains checks from patterns
        for pat in self._patterns:
            if not pat.body_contains:
                continue
            matches = sum(1 for kw in pat.body_contains if kw in text)
            ratio = matches / len(pat.body_contains)
            if ratio >= 0.5:
                candidate = pat.confidence * ratio * 0.6
                if candidate > score:
                    score = candidate
                    service = pat.service_type

        return min(score, 1.0), service


# Singleton
_db: Optional[SignatureDB] = None


def get_signature_db() -> SignatureDB:
    global _db
    if _db is None:
        _db = SignatureDB()
    return _db

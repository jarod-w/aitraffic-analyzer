"""AI traffic metadata extractor."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from prism.models import AIMetadata, FileUploadInfo


# Headers whose values indicate the AI client version / app version
_CLIENT_VERSION_HEADERS = ["x-client-version", "x-app-version", "x-stainless-runtime-version"]
_APP_VERSION_HEADERS = ["x-app-version", "x-ds-app-version"]
_PLATFORM_HEADERS = ["x-client-platform", "x-ds-platform", "x-platform"]

# Custom header prefixes to capture
_AI_HEADER_PREFIXES = [
    "x-api-", "x-client-", "x-app-", "x-model-",
    "x-ds-", "x-thinking-", "x-file-", "anthropic-",
    "openai-", "x-stainless-",
]


class MetadataExtractor:
    """Extracts structured metadata from a captured HTTP request/response pair."""

    def extract(
        self,
        *,
        provider: str,
        method: str,
        url: str,
        request_headers: dict[str, str],
        request_body: Optional[bytes],
        response_headers: Optional[dict[str, str]],
        response_body: Optional[bytes],
        timestamp: Optional[datetime] = None,
    ) -> AIMetadata:
        norm_req = {k.lower(): v for k, v in request_headers.items()}
        norm_resp = {k.lower(): v for k, v in (response_headers or {}).items()}

        req_json = self._try_parse_json(request_body)
        resp_json = self._try_parse_json(response_body)

        return AIMetadata(
            provider=provider,
            model_name=self._extract_model(url, req_json, resp_json, norm_req),
            api_version=self._extract_api_version(url, norm_req),
            user_agent=norm_req.get("user-agent", ""),
            client_version=self._extract_first(norm_req, _CLIENT_VERSION_HEADERS),
            app_version=self._extract_first(norm_req, _APP_VERSION_HEADERS),
            platform=self._extract_first(norm_req, _PLATFORM_HEADERS),
            auth_type=self._classify_auth(norm_req),
            is_streaming=self._detect_streaming(req_json, norm_resp),
            thinking_enabled=self._detect_thinking(req_json, norm_req),
            file_upload=self._extract_file_upload(method, request_headers, request_body),
            custom_headers=self._extract_custom_headers(norm_req),
            timestamp=timestamp or datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _try_parse_json(self, body: Optional[bytes]) -> Optional[dict]:
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, AttributeError):
            return None

    def _extract_model(
        self,
        url: str,
        req_json: Optional[dict],
        resp_json: Optional[dict],
        norm_headers: dict[str, str],
    ) -> Optional[str]:
        # 1. From request body
        if req_json and "model" in req_json:
            return str(req_json["model"])

        # 2. From response body
        if resp_json and "model" in resp_json:
            return str(resp_json["model"])

        # 3. From URL path (e.g., /models/gpt-4o/completions)
        match = re.search(r"/models?/([a-zA-Z0-9\-_.:/]+)", url)
        if match:
            return match.group(1).rstrip("/")

        # 4. From custom headers
        for hdr in ["x-model", "x-model-id", "x-deployment-model"]:
            if hdr in norm_headers:
                return norm_headers[hdr]

        return None

    def _extract_api_version(self, url: str, norm_headers: dict[str, str]) -> Optional[str]:
        # From header
        for hdr in ["anthropic-version", "api-version", "openai-version"]:
            if hdr in norm_headers:
                return norm_headers[hdr]

        # From URL query parameter
        match = re.search(r"api-version=([^&]+)", url)
        if match:
            return match.group(1)

        # From URL path version prefix
        match = re.search(r"/(v\d+(?:\.\d+)?)/", url)
        if match:
            return match.group(1)

        return None

    def _classify_auth(self, norm_headers: dict[str, str]) -> str:
        auth = norm_headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return "Bearer Token"
        if auth.lower().startswith("basic "):
            return "Basic Auth"
        if "x-api-key" in norm_headers:
            return "API Key (x-api-key)"
        if "cookie" in norm_headers:
            return "Cookie Session"
        return "Unknown"

    def _detect_streaming(
        self, req_json: Optional[dict], norm_resp_headers: dict[str, str]
    ) -> bool:
        if req_json and req_json.get("stream") is True:
            return True
        content_type = norm_resp_headers.get("content-type", "")
        return "text/event-stream" in content_type

    def _detect_thinking(
        self, req_json: Optional[dict], norm_headers: dict[str, str]
    ) -> Optional[bool]:
        # Anthropic extended thinking
        if req_json:
            thinking = req_json.get("thinking", {})
            if isinstance(thinking, dict) and "type" in thinking:
                return thinking.get("type") == "enabled"

        # DeepSeek thinking header
        val = norm_headers.get("x-thinking-enabled")
        if val is not None:
            return val.strip() not in ("0", "false", "no")

        return None

    def _extract_file_upload(
        self,
        method: str,
        request_headers: dict[str, str],
        request_body: Optional[bytes],
    ) -> Optional[FileUploadInfo]:
        if method.upper() != "POST":
            return None

        content_type = next(
            (v for k, v in request_headers.items() if k.lower() == "content-type"), ""
        )
        if "multipart/form-data" not in content_type:
            return None

        # Best-effort extraction from headers
        norm = {k.lower(): v for k, v in request_headers.items()}
        filename = None
        size_str = norm.get("x-file-size")
        size = int(size_str) if size_str and size_str.isdigit() else len(request_body or b"")

        # Try to find filename in body
        if request_body:
            m = re.search(
                rb'Content-Disposition:[^\r\n]*filename="([^"]+)"',
                request_body,
                re.IGNORECASE,
            )
            if m:
                filename = m.group(1).decode("utf-8", errors="replace")

        if filename is None:
            return None

        # SHA256 of body
        import hashlib
        sha = hashlib.sha256(request_body).hexdigest() if request_body else None

        return FileUploadInfo(
            filename=filename,
            size=size,
            content_type=content_type,
            sha256=sha,
        )

    def _extract_custom_headers(self, norm_headers: dict[str, str]) -> dict[str, str]:
        return {
            k: v
            for k, v in norm_headers.items()
            if any(k.startswith(p) for p in _AI_HEADER_PREFIXES)
        }

    def _extract_first(self, norm_headers: dict[str, str], keys: list[str]) -> Optional[str]:
        for k in keys:
            if k in norm_headers:
                return norm_headers[k]
        return None

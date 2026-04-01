"""PrismPage — extended Playwright Page API for user interaction scripts."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class PrismHelper:
    """
    Attached to PrismPage as `page.prism`.
    Provides PRISM-specific helper methods for user scripts.
    """

    def __init__(self, page):
        self._page = page
        self._phases: list[dict] = []

    async def wait_for_ai_response(self, timeout: int = 60_000):
        """
        Wait until an AI response stream appears to have finished.

        Heuristic: wait for networkidle (no pending requests for 500ms)
        with a generous timeout, then wait for DOM to stop changing.
        """
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass

        # Additional DOM-settle check
        await self._wait_for_dom_stable(timeout_ms=5000)

    async def wait_for_upload_complete(self, timeout: int = 30_000):
        """Wait for a file upload to finish (networkidle heuristic)."""
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass

    def mark_phase(self, label: str):
        """Record a named phase boundary for report annotation."""
        self._phases.append({"label": label, "timestamp": datetime.utcnow().isoformat()})
        logger.debug("PRISM phase: %s", label)

    @property
    def phases(self) -> list[dict]:
        return list(self._phases)

    async def _wait_for_dom_stable(self, timeout_ms: int = 3000, poll_ms: int = 300):
        """Poll until the page HTML stops changing."""
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        prev_html = await self._page.content()
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_ms / 1000)
            current_html = await self._page.content()
            if current_html == prev_html:
                return
            prev_html = current_html


class PrismPage:
    """
    Wraps a Playwright Page and exposes the full Playwright API plus
    a `.prism` helper namespace.

    User scripts receive a PrismPage instance as their `page` argument.
    """

    def __init__(self, page):
        self._page = page
        self.prism = PrismHelper(page)

    def __getattr__(self, name: str):
        """Proxy all unknown attribute accesses to the underlying Playwright Page."""
        return getattr(self._page, name)

    # Make PrismPage usable as an async context manager (for with page: patterns)
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

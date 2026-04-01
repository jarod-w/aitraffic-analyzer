"""Active Probe Module — launches a browser via Playwright + mitmproxy to capture AI traffic."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from prism.config import settings
from prism.models import AITrafficRecord, Credentials, ProbeTask

logger = logging.getLogger(__name__)


class ActiveProbe:
    """
    Orchestrates:
    1. Starting mitmproxy as an in-process proxy
    2. Launching a Playwright browser pointed at the proxy
    3. Navigating to target URLs + performing interactions
    4. Collecting captured AI traffic records
    """

    def __init__(self, task: ProbeTask, on_record: Optional[Callable] = None):
        self.task = task
        self.on_record = on_record
        self._records: list[AITrafficRecord] = []
        self._proxy_proc: Optional[asyncio.subprocess.Process] = None

    async def run(self) -> list[AITrafficRecord]:
        """Full probe lifecycle — returns list of captured records."""
        async with self._mitm_context() as proxy_port:
            async with self._browser_context(proxy_port) as (browser, context):
                for url in self.task.urls:
                    try:
                        await self._probe_url(context, url)
                    except Exception as e:
                        logger.warning("Error probing %s: %s", url, e)
        return self._records

    # ------------------------------------------------------------------
    # mitmproxy context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _mitm_context(self):
        """Start mitmproxy as a subprocess and yield the proxy port."""
        from prism.capture.mitm import PrismAddon

        addon = PrismAddon(
            task_id=self.task.task_id,
            on_record=self._collect_record,
        )

        from mitmproxy.options import Options
        from mitmproxy.tools.dump import DumpMaster

        opts = Options(
            listen_host=settings.mitm_host,
            listen_port=settings.mitm_port,
        )

        if settings.ssl_keylog_file:
            os.environ["SSLKEYLOGFILE"] = settings.ssl_keylog_file

        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(addon)

        task = asyncio.create_task(master.run_async())
        await asyncio.sleep(0.5)  # brief warmup

        try:
            yield settings.mitm_port
        finally:
            master.shutdown()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @asynccontextmanager
    async def _browser_context(self, proxy_port: int):
        """Launch Playwright Chromium through the MITM proxy."""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                proxy={"server": f"http://{settings.mitm_host}:{proxy_port}"},
            )
            context = await browser.new_context(
                ignore_https_errors=True,
            )

            # Inject credentials at context level if needed
            if self.task.credentials:
                await self._apply_credentials_to_context(context)

            try:
                yield browser, context
            finally:
                await context.close()
                await browser.close()

    # ------------------------------------------------------------------
    # URL probing
    # ------------------------------------------------------------------

    async def _probe_url(self, context, url: str):
        from playwright.async_api import Page

        page = await context.new_page()
        try:
            await page.goto(url, timeout=self.task.capture_timeout * 1000, wait_until="networkidle")

            if self.task.credentials and self.task.credentials.auth_type == "form":
                await self._do_form_login(page, self.task.credentials)

            if self.task.interaction_mode == "script" and self.task.playwright_script:
                await self._run_user_script(page, self.task.playwright_script)
            else:
                await self._auto_interact(page)

            # Wait for any pending requests to complete
            await page.wait_for_load_state("networkidle", timeout=30_000)
        finally:
            await page.close()

    # ------------------------------------------------------------------
    # Interaction modes
    # ------------------------------------------------------------------

    async def _auto_interact(self, page):
        """
        Heuristic auto-detection: find an AI chat input, type a probe message,
        and wait for the response to settle.
        """
        PROBE_TEXT = "Hello, this is a test message from PRISM."
        INPUT_SELECTORS = [
            "textarea[placeholder*='Ask' i]",
            "textarea[placeholder*='Message' i]",
            "textarea[placeholder*='Prompt' i]",
            "textarea[placeholder*='Chat' i]",
            "div[contenteditable='true'][placeholder*='Ask' i]",
            "div[contenteditable='true']",
            "textarea",
            "input[type='text'][placeholder*='Ask' i]",
        ]

        for selector in INPUT_SELECTORS:
            try:
                el = await page.wait_for_selector(selector, timeout=3_000)
                if el:
                    await el.fill(PROBE_TEXT)
                    await page.keyboard.press("Enter")
                    # Wait for network to settle after submission
                    await page.wait_for_load_state("networkidle", timeout=30_000)
                    return
            except Exception:
                continue

        logger.debug("auto_interact: no input found on %s", page.url)

    async def _run_user_script(self, page, script_path: str):
        """Load and execute a user-supplied Playwright script."""
        from prism.scripting.prism_page import PrismPage

        path = Path(script_path)
        if not path.exists():
            raise FileNotFoundError(f"Playwright script not found: {script_path}")

        spec = importlib.util.spec_from_file_location("user_script", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        prism_page = PrismPage(page)
        await module.run(prism_page)

    # ------------------------------------------------------------------
    # Login helpers
    # ------------------------------------------------------------------

    async def _apply_credentials_to_context(self, context):
        creds = self.task.credentials
        if creds.auth_type == "cookie" and creds.cookies:
            await context.add_cookies(
                [{"name": k, "value": v, "url": self.task.urls[0]} for k, v in creds.cookies.items()]
            )

    async def _do_form_login(self, page, creds: Credentials):
        try:
            login_url = creds.login_url or page.url
            if creds.login_url:
                await page.goto(login_url, wait_until="networkidle")

            user_sel = creds.username_selector or "input[type='email'],input[name*='user' i],input[name*='email' i]"
            pass_sel = creds.password_selector or "input[type='password']"
            submit_sel = creds.submit_selector or "button[type='submit'],input[type='submit']"

            await page.fill(user_sel, creds.username or "")
            await page.fill(pass_sel, creds.password or "")
            await page.click(submit_sel)
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            logger.warning("Form login failed: %s", e)

    # ------------------------------------------------------------------
    # Record collection
    # ------------------------------------------------------------------

    async def _collect_record(self, record: AITrafficRecord):
        self._records.append(record)
        if self.on_record:
            await self.on_record(record)

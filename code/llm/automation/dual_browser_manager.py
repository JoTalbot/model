"""
Dual Browser & Profile Manager for AIOS / Project Octopus.
Manages both Google accounts / browser profiles simultaneously:
- Primary: jo.talbot@gmail.com (CDP 9222, noVNC 6080)
- Secondary: autohelp.seo.manager@gmail.com (CDP 9224, noVNC 6081)
"""

import os
import json
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

PRIMARY_CDP = "http://127.0.0.1:9222"
SECONDARY_CDP = "http://127.0.0.1:9224"

class DualBrowserManager:
    def __init__(self, primary_url=PRIMARY_CDP, secondary_url=SECONDARY_CDP):
        self.primary_url = primary_url
        self.secondary_url = secondary_url
        self._pw = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._pw:
            self._pw.stop()

    def get_context(self, profile: str = "primary") -> BrowserContext:
        """
        Returns the browser context for either 'primary' or 'secondary'.
        """
        if not self._pw:
            self._pw = sync_playwright().start()
        
        target_cdp = self.primary_url if profile == "primary" else self.secondary_url
        browser = self._pw.chromium.connect_over_cdp(target_cdp)
        if browser.contexts:
            return browser.contexts[0]
        return browser.new_context()

    def get_page(self, profile: str = "primary", url: str = None) -> Page:
        """
        Opens or reuses a page in the specified profile.
        """
        ctx = self.get_context(profile)
        page = ctx.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page

    def get_status(self) -> dict:
        """
        Checks health and connectivity of both profiles.
        """
        status = {"primary": False, "secondary": False, "details": {}}
        
        # Test Primary
        try:
            ctx1 = self.get_context("primary")
            status["primary"] = True
            status["details"]["primary"] = {
                "cdp": self.primary_url,
                "novnc_port": 6080,
                "pages_open": len(ctx1.pages),
                "account": "jo.talbot@gmail.com"
            }
        except Exception as e:
            status["details"]["primary"] = {"error": str(e)}

        # Test Secondary
        try:
            ctx2 = self.get_context("secondary")
            status["secondary"] = True
            status["details"]["secondary"] = {
                "cdp": self.secondary_url,
                "novnc_port": 6081,
                "pages_open": len(ctx2.pages),
                "account": "autohelp.seo.manager@gmail.com"
            }
        except Exception as e:
            status["details"]["secondary"] = {"error": str(e)}

        return status

if __name__ == "__main__":
    with DualBrowserManager() as mgr:
        res = mgr.get_status()
        print(json.dumps(res, indent=2, ensure_ascii=False))

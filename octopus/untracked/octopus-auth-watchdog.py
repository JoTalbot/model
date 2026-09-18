"""
Auth Watchdog & Auto-Harvest Trigger for Secondary Profile.
Monitors Google authentication status in liza-browser-profile9 (:9224)
and automatically launches key provisioning as soon as Google login completes.
"""

import time, json, subprocess
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9224"

def check_login_state():
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            cookies = context.cookies()
            sid_cookies = [c for c in cookies if c.get("name") in ("SID", "SSID", "HSID", "SAPISID") and "google" in c.get("domain", "")]
            if len(sid_cookies) >= 2:
                return True
    except Exception:
        pass
    return False

def main():
    print("Watching for Google authentication on Secondary Profile (:9224)...")
    while True:
        if check_login_state():
            print("🎉 Google Authentication detected on Secondary Profile! Launching key provisioning...")
            subprocess.run(["/opt/aios-venv/bin/python3", "/opt/octopus/octopus-provider-provisioner.py", "run-all", "--profile", "secondary"])
            break
        time.sleep(10)

if __name__ == "__main__":
    main()

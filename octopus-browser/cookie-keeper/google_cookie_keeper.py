#!/usr/bin/env python3
"""Keep the jo.talbot Google session alive across browser restarts.

- If the browser currently has a live Google login -> export cookies to vault.
- Else, if a vault exists -> inject it and reload Gemini.
Run every 2 minutes from a systemd timer.
"""
import json, time, sys, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
VAULT = Path("/opt/octopus-browser/data/cookies/google.json")
URLS = ["https://google.com", "https://www.google.com", "https://accounts.google.com",
        "https://gemini.google.com", "https://mail.google.com", "https://chat.google.com",
        "https://drive.google.com", "https://docs.google.com"]
REQUIRED = {"SID", "HSID", "__Secure-1PSID", "__Secure-3PSID"}
KEEP = REQUIRED | {"SSID", "SAPISID", "APISID", "LSID", "__Host-1PLSID", "__Host-3PLSID",
                   "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
                   "__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
                   "SIDCC", "NID", "GAPS", "__Secure-ENID", "AEC"}

def cdp_ready():
    try:
        urllib.request.urlopen(CDP + "/json/version", timeout=3)
        return True
    except Exception:
        return False

def main():
    if not cdp_ready():
        print("CDP down; skip"); return 0
    expires = int(time.time()) + 365 * 24 * 3600
    with sync_playwright() as p:
        # FIX 2026-09-17 (аудит P1-3): таймаут на CDP-коннект, иначе висели до TimeoutStartSec=120
        b = p.chromium.connect_over_cdp(CDP, timeout=15000)
        ctx = b.contexts[0]
        live = ctx.cookies(URLS)
        names = {c["name"] for c in live}
        if REQUIRED <= names:
            seen, keep = set(), []
            for c in live:
                if "google.com" not in c.get("domain", ""):
                    continue
                if c["name"] not in KEEP and not c["name"].startswith("__Secure-"):
                    continue
                k = (c["domain"], c["name"], c["path"])
                if k in seen:
                    continue
                seen.add(k)
                keep.append({"name": c["name"], "value": c["value"], "domain": c["domain"],
                             "path": c["path"], "expires": expires,
                             "httpOnly": c.get("httpOnly", False), "secure": c.get("secure", True),
                             "sameSite": c.get("sameSite") or "Lax"})
            VAULT.parent.mkdir(parents=True, exist_ok=True)
            tmp = VAULT.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(keep))
            tmp.replace(VAULT)
            print(f"vault updated: {len(keep)} cookies")
            b.close()
            return 0
        # not logged in -> restore
        if VAULT.exists():
            cookies = json.loads(VAULT.read_text())
            # PSIDTS/PSIDRTS/PSIDCC/SIDCC are one-time rotating tokens. Replaying
            # a consumed PSIDTS makes Google revoke the whole session server-side,
            # so drop them: Google issues fresh ones against the long-lived SID set.
            DROP = {"__Secure-1PSIDTS", "__Secure-3PSIDTS",
                    "__Secure-1PSIDRTS", "__Secure-3PSIDRTS",
                    "__Secure-1PSIDCC", "__Secure-3PSIDCC", "SIDCC"}
            cookies = [c for c in cookies if c["name"] not in DROP]
            for c in cookies:
                c["expires"] = expires
            ctx.add_cookies(cookies)
            page = next((x for x in ctx.pages if "gemini.google.com" in x.url), None)
            if page is None:
                page = ctx.new_page()
            page.goto("https://gemini.google.com/app", wait_until="commit", timeout=25000)
            time.sleep(8)
            after = {c["name"] for c in ctx.cookies(["https://gemini.google.com", "https://google.com"])}
            ok = REQUIRED <= after
            print(f"restore attempted ({len(cookies)} cookies), session ok: {ok}")
            b.close()
            return 0 if ok else 1
        print("not authenticated and no vault")
        b.close()
        return 0

if __name__ == "__main__":
    # FIX 2026-09-17 (аудит P1-3): транзиентные сбои браузера/CDP/Google не должны
    # ронять systemd-юнит каждые 2 минуты (666 failed за сутки). Ошибка логируется,
    # юнит завершается успешно; реальная проблема видна в journal и по cookie-возрасту.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"skip: {type(exc).__name__}: {str(exc)[:200]}")
        sys.exit(0)

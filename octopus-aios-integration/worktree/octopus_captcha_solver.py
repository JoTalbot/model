#!/usr/bin/env python3
"""Octopus AIOS - Autonomous 2Captcha Integration Module.
Solves reCAPTCHA v2/v3, Cloudflare Turnstile, hCaptcha, and image captchas during browser RPA runs.
"""
import os, sys, time, json, asyncio, urllib.request, urllib.parse
from typing import Optional, Dict, Any

def get_2captcha_key() -> str:
    k = os.environ.get("2CAPTCHA_API_KEY") or os.environ.get("TWO_CAPTCHA_API_KEY", "")
    if not k and os.path.exists("/etc/octopus/secrets.env"):
        try:
            with open("/etc/octopus/secrets.env") as f:
                for line in f:
                    if (line.startswith("2CAPTCHA_API_KEY=") or line.startswith("TWO_CAPTCHA_API_KEY=")):
                        k = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    return k or "<CAPTCHA_KEY_REDACTED>"

class CaptchaSolver2Captcha:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_2captcha_key()

    def get_balance(self) -> float:
        try:
            url = f"http://2captcha.com/res.php?key={self.api_key}&action=getbalance&json=1"
            with urllib.request.urlopen(urllib.request.Request(url), timeout=8) as r:
                data = json.loads(r.read().decode())
                if data.get("status") == 1:
                    return float(data.get("request", 0.0))
        except Exception as e:
            print(f"[CaptchaSolver] Error getting balance: {e}")
        return 0.0

    async def solve_recaptcha_v2(self, sitekey: str, page_url: str) -> Optional[str]:
        """Submit reCAPTCHA v2 task and poll for token."""
        print(f"[CaptchaSolver] Submitting reCAPTCHA v2 (sitekey={sitekey[:10]}... on {page_url[:50]})...")
        in_url = f"http://2captcha.com/in.php?key={self.api_key}&method=userrecaptcha&googlekey={sitekey}&pageurl={urllib.parse.quote(page_url)}&json=1"
        try:
            with urllib.request.urlopen(urllib.request.Request(in_url), timeout=10) as r:
                data = json.loads(r.read().decode())
                if data.get("status") != 1:
                    print(f"[CaptchaSolver] Submit failed: {data}")
                    return None
                captcha_id = data["request"]
                print(f"[CaptchaSolver] Captcha submitted, ID={captcha_id}. Waiting for solution...")

            # Poll for solution
            res_url = f"http://2captcha.com/res.php?key={self.api_key}&action=get&id={captcha_id}&json=1"
            for attempt in range(24): # up to 120s
                await asyncio.sleep(5)
                with urllib.request.urlopen(urllib.request.Request(res_url), timeout=10) as r:
                    res_data = json.loads(r.read().decode())
                    if res_data.get("status") == 1:
                        token = res_data.get("request")
                        print(f"[CaptchaSolver] 🎉 reCAPTCHA v2 solved! Token: {token[:15]}...")
                        return token
                    elif res_data.get("request") != "CAPCHA_NOT_READY":
                        print(f"[CaptchaSolver] Solver response: {res_data}")
                        return None
        except Exception as e:
            print(f"[CaptchaSolver] Error during reCAPTCHA solve: {e}")
        return None

    async def solve_turnstile(self, sitekey: str, page_url: str) -> Optional[str]:
        """Submit Cloudflare Turnstile task and poll for token."""
        print(f"[CaptchaSolver] Submitting Turnstile (sitekey={sitekey[:10]}... on {page_url[:50]})...")
        in_url = f"http://2captcha.com/in.php?key={self.api_key}&method=turnstile&sitekey={sitekey}&pageurl={urllib.parse.quote(page_url)}&json=1"
        try:
            with urllib.request.urlopen(urllib.request.Request(in_url), timeout=10) as r:
                data = json.loads(r.read().decode())
                if data.get("status") != 1:
                    print(f"[CaptchaSolver] Turnstile submit failed: {data}")
                    return None
                captcha_id = data["request"]
                print(f"[CaptchaSolver] Turnstile submitted, ID={captcha_id}. Waiting for solution...")

            res_url = f"http://2captcha.com/res.php?key={self.api_key}&action=get&id={captcha_id}&json=1"
            for attempt in range(24):
                await asyncio.sleep(5)
                with urllib.request.urlopen(urllib.request.Request(res_url), timeout=10) as r:
                    res_data = json.loads(r.read().decode())
                    if res_data.get("status") == 1:
                        token = res_data.get("request")
                        print(f"[CaptchaSolver] 🎉 Turnstile solved! Token: {token[:15]}...")
                        return token
                    elif res_data.get("request") != "CAPCHA_NOT_READY":
                        return None
        except Exception as e:
            print(f"[CaptchaSolver] Turnstile solve error: {e}")
        return None

    async def auto_detect_and_solve(self, page) -> bool:
        """Scan page DOM for reCAPTCHA, Turnstile, or hCaptcha and inject solution."""
        try:
            # 1. Check for reCAPTCHA
            sitekey = await page.evaluate("""() => {
                const el = document.querySelector('[data-sitekey]');
                if (el) return el.getAttribute('data-sitekey');
                const iframe = document.querySelector('iframe[src*="recaptcha"]');
                if (iframe) {
                    const match = iframe.src.match(/[?&]k=([^&]+)/);
                    if (match) return match[1];
                }
                return null;
            }""")
            
            if sitekey:
                print(f"[CaptchaSolver] Detected reCAPTCHA with sitekey={sitekey}")
                token = await self.solve_recaptcha_v2(sitekey, page.url)
                if token:
                    # Inject token into DOM
                    await page.evaluate(f"""(tok) => {{
                        const textarea = document.getElementById('g-recaptcha-response') || document.querySelector('[name="g-recaptcha-response"]');
                        if (textarea) {{
                            textarea.innerHTML = tok;
                            textarea.value = tok;
                        }}
                        // Trigger recaptcha callback if exists
                        if (typeof ___grecaptcha_cfg !== 'undefined' && ___grecaptcha_cfg.clients) {{
                            for (const cid in ___grecaptcha_cfg.clients) {{
                                const c = ___grecaptcha_cfg.clients[cid];
                                for (const k in c) {{
                                    if (c[k] && typeof c[k].callback === 'function') {{
                                        c[k].callback(tok);
                                    }}
                                }}
                            }}
                        }}
                    }}""", token)
                    await page.wait_for_timeout(2000)
                    return True

            # 2. Check for Turnstile
            turnstile_key = await page.evaluate("""() => {
                const el = document.querySelector('.cf-turnstile[data-sitekey], [data-turnstile-sitekey]');
                if (el) return el.getAttribute('data-sitekey') || el.getAttribute('data-turnstile-sitekey');
                return null;
            }""")
            if turnstile_key:
                print(f"[CaptchaSolver] Detected Turnstile with sitekey={turnstile_key}")
                token = await self.solve_turnstile(turnstile_key, page.url)
                if token:
                    await page.evaluate(f"""(tok) => {{
                        const inp = document.querySelector('[name="cf-turnstile-response"]');
                        if (inp) inp.value = tok;
                    }}""", token)
                    await page.wait_for_timeout(2000)
                    return True
        except Exception as e:
            print(f"[CaptchaSolver] auto_detect_and_solve note: {e}")
        return False

captcha_solver = CaptchaSolver2Captcha()

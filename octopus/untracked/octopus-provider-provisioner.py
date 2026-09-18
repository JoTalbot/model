#!/usr/bin/env python3
"""Octopus AIOS - Universal Multi-Profile Multi-Provider Google OAuth AI Key Provisioner & 2Captcha Vision Auditor.
Supports:
- Primary Profile (jo.talbot@gmail.com, CDP :9222, noVNC :6080)
- Secondary Profile (autohelp.seo.manager@gmail.com, CDP :9224, noVNC :6081)
- 14 AI platforms with automated reCAPTCHA/Turnstile solving via 2Captcha
- Dynamic multi-key array harvesting (GEMINI_API_KEYS, GROQ_API_KEYS, MISTRAL_API_KEYS)
"""
import os, sys, time, json, re, argparse, urllib.request, subprocess, threading
from pathlib import Path
from typing import Dict, Any, List, Optional

SECRETS_FILE = "/etc/octopus/secrets.env"
BALANCER_RELOAD_URL = "http://127.0.0.1:8080/api/balancer/reload"
SCREENSHOTS_DIR = Path("/opt/octopus_rpa_screenshots")

SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
Path("/run/octopus").mkdir(parents=True, exist_ok=True)

try:
    from octopus_captcha_solver import captcha_solver
except Exception:
    sys.path.insert(0, '/opt')
    try:
        from octopus_captcha_solver import captcha_solver
    except Exception:
        captcha_solver = None

PROFILE_CONFIGS = {
    "primary": {
        "cdp_url": "http://127.0.0.1:9222",
        "novnc_url": "http://<PUBLIC_IP_REDACTED>:6080/vnc.html",
        "novnc_port": 6080,
        "email": "jo.talbot@gmail.com",
        "tag": "PRIMARY",
        "status_file": Path("/run/octopus/provisioner_job_primary.json")
    },
    "secondary": {
        "cdp_url": "http://127.0.0.1:9224",
        "novnc_url": "http://<PUBLIC_IP_REDACTED>:6081/vnc.html",
        "novnc_port": 6081,
        "email": "autohelp.seo.manager@gmail.com",
        "tag": "AUTOHelp",
        "status_file": Path("/run/octopus/provisioner_job_secondary.json")
    }
}

SUPPORTED_PROVIDERS = [
    {
        "id": "aistudio",
        "name": "Google AI Studio",
        "env_var": "GEMINI_API_KEY",
        "url": "https://aistudio.google.com/app/apikey",
        "models": ["gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-thinking"],
        "api_endpoint": "https://generativelanguage.googleapis.com"
    },
    {
        "id": "groq",
        "name": "Groq Cloud Console",
        "env_var": "GROQ_API_KEY",
        "url": "https://console.groq.com/keys",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b", "mixtral-8x7b-32768"],
        "api_endpoint": "https://api.groq.com/openai/v1"
    },
    {
        "id": "cerebras",
        "name": "Cerebras Cloud",
        "env_var": "CEREBRAS_API_KEY",
        "url": "https://cloud.cerebras.ai/",
        "models": ["llama3.3-70b", "llama3.1-8b"],
        "api_endpoint": "https://api.cerebras.ai/v1"
    },
    {
        "id": "sambanova",
        "name": "SambaNova Cloud",
        "env_var": "SAMBANOVA_API_KEY",
        "url": "https://cloud.sambanova.ai/apis",
        "models": ["Meta-Llama-3.1-405B-Instruct", "Meta-Llama-3.3-70B-Instruct", "DeepSeek-R1"],
        "api_endpoint": "https://api.sambanova.ai/v1"
    },
    {
        "id": "openrouter",
        "name": "OpenRouter AI",
        "env_var": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/settings/keys",
        "models": ["meta-llama/llama-3.3-70b-instruct", "google/gemini-2.0-flash-exp:free", "deepseek/deepseek-r1:free"],
        "api_endpoint": "https://openrouter.ai/api/v1"
    },
    {
        "id": "hyperbolic",
        "name": "Hyperbolic AI",
        "env_var": "HYPERBOLIC_API_KEY",
        "url": "https://app.hyperbolic.xyz/settings",
        "models": ["deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-72B-Instruct"],
        "api_endpoint": "https://api.hyperbolic.xyz/v1"
    },
    {
        "id": "together",
        "name": "Together AI",
        "env_var": "TOGETHER_API_KEY",
        "url": "https://api.together.xyz/settings/api-keys",
        "models": ["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "mistralai/Mixtral-8x7B-Instruct-v0.1"],
        "api_endpoint": "https://api.together.xyz/v1"
    },
    {
        "id": "mistral",
        "name": "Mistral AI Console",
        "env_var": "MISTRAL_API_KEY",
        "url": "https://console.mistral.ai/api-keys/",
        "models": ["mistral-large-latest", "mistral-small-latest", "codestral-latest"],
        "api_endpoint": "https://api.mistral.ai/v1"
    },
    {
        "id": "cohere",
        "name": "Cohere Platform",
        "env_var": "COHERE_API_KEY",
        "url": "https://dashboard.cohere.com/api-keys",
        "models": ["command-r-plus", "command-r"],
        "api_endpoint": "https://api.cohere.com/v2"
    },
    {
        "id": "huggingface",
        "name": "Hugging Face Hub",
        "env_var": "HF_TOKEN",
        "url": "https://huggingface.co/settings/tokens",
        "models": ["Qwen/Qwen2.5-72B-Instruct", "meta-llama/Meta-Llama-3.1-8B-Instruct"],
        "api_endpoint": "https://api-inference.huggingface.co"
    },
    {
        "id": "deepseek",
        "name": "DeepSeek Platform",
        "env_var": "DEEPSEEK_API_KEY",
        "url": "https://platform.deepseek.com/api_keys",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_endpoint": "https://api.deepseek.com"
    },
    {
        "id": "novita",
        "name": "Novita AI",
        "env_var": "NOVITA_API_KEY",
        "url": "https://novita.ai/settings/key-management",
        "models": ["meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-r1"],
        "api_endpoint": "https://api.novita.ai/v3/openai"
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "env_var": "SILICONFLOW_API_KEY",
        "url": "https://cloud.siliconflow.cn/account/ak",
        "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-Coder-32B-Instruct"],
        "api_endpoint": "https://api.siliconflow.cn/v1"
    },
    {
        "id": "github_models",
        "name": "GitHub Models",
        "env_var": "GITHUB_TOKEN",
        "url": "https://github.com/settings/tokens",
        "models": ["gpt-4o", "claude-3-5-sonnet", "Meta-Llama-3.1-70B-Instruct"],
        "api_endpoint": "https://models.inference.ai.azure.com"
    }
]

def load_current_secrets() -> Dict[str, str]:
    secrets = {}
    if os.path.exists(SECRETS_FILE):
        try:
            with open(SECRETS_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        secrets[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    return secrets

def save_secret_key(env_var: str, key_value: str, account_tag: Optional[str] = None) -> bool:
    if not key_value:
        return False
    current = load_current_secrets()
    if not current.get(env_var):
        current[env_var] = key_value
    
    multi_var = f"{env_var}S" if not env_var.endswith("S") else env_var
    existing_keys = [k.strip() for k in current.get(multi_var, "").split(",") if k.strip()]
    if key_value not in existing_keys:
        existing_keys.append(key_value)
    current[multi_var] = ",".join(existing_keys)
    
    if account_tag:
        clean_tag = re.sub(r'[^A-Za-z0-9_]', '_', account_tag).upper()
        current[f"{env_var}_{clean_tag}"] = key_value

    try:
        os.makedirs(os.path.dirname(SECRETS_FILE), exist_ok=True)
        with open(SECRETS_FILE, "w") as f:
            f.write("# Octopus AIOS Unified Secrets & LLM Provider API Keys\n")
            f.write(f"# Auto-updated by octopus-provider-provisioner at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n")
            for k, v in sorted(current.items()):
                f.write(f"{k}=\"{v}\"\n")
        os.chmod(SECRETS_FILE, 0o600)
        return True
    except Exception:
        return False

def notify_llmbalancer_reload():
    try:
        req = urllib.request.Request(BALANCER_RELOAD_URL, data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False

def update_job_status(status_dict: Dict[str, Any], status_file: Path):
    try:
        status_file.write_text(json.dumps(status_dict, indent=2, ensure_ascii=False), encoding='utf-8')
        # Also mirror to default /run/octopus/provisioner_job.json
        Path("/run/octopus/provisioner_job.json").write_text(json.dumps(status_dict, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass

def get_job_status(profile: str = "primary") -> Dict[str, Any]:
    cfg = PROFILE_CONFIGS.get(profile, PROFILE_CONFIGS["primary"])
    st_file = cfg["status_file"]
    if st_file.exists():
        try:
            return json.loads(st_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {"state": "idle", "profile": profile, "progress": 0, "current": None, "logs": [], "results": []}

class UniversalVisionProvisioner:
    def __init__(self, profile: str = "primary", custom_cdp: Optional[str] = None, custom_email: Optional[str] = None):
        self.profile = profile
        cfg = PROFILE_CONFIGS.get(profile, PROFILE_CONFIGS["primary"])
        self.cdp_endpoint = custom_cdp or cfg["cdp_url"]
        self.target_email = custom_email or cfg["email"]
        self.tag = cfg["tag"]
        self.status_file = cfg["status_file"]
        self.novnc_port = cfg["novnc_port"]
        self.novnc_url = cfg["novnc_url"]
        self.browser = None
        self.context = None
        self.active_google_account = self.target_email

    async def connect(self):
        from playwright.async_api import async_playwright
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.connect_over_cdp(self.cdp_endpoint)
        self.context = self.browser.contexts[0]
        await self.detect_active_google_account()

    async def detect_active_google_account(self) -> Optional[str]:
        try:
            for page in self.context.pages:
                if "google.com" in page.url:
                    labels = await page.eval_on_selector_all("[aria-label]", "els => els.map(e => e.getAttribute('aria-label'))")
                    for l in labels:
                        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', l or "")
                        if match:
                            self.active_google_account = match.group(0)
                            return self.active_google_account
        except Exception:
            pass
        return self.active_google_account or self.target_email

    async def provision_single(self, p_meta: Dict[str, Any], job_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p_id = p_meta["id"]
        res = {
            "provider": p_id,
            "name": p_meta["name"],
            "url": p_meta["url"],
            "status": "pending",
            "key": None,
            "screenshot": None,
            "error": None
        }
        
        page = await self.context.new_page()
        try:
            await page.set_viewport_size({"width": 1280, "height": 800})
            if job_state:
                job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] [{self.profile.upper()}] 🌐 Переход на {p_meta['name']} ({p_meta['url']})...")
                update_job_status(job_state, self.status_file)

            await page.goto(p_meta["url"], wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)

            # Solve captchas via 2Captcha if present
            if captcha_solver:
                has_captcha = await captcha_solver.auto_detect_and_solve(page)
                if has_captcha and job_state:
                    job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] 🧩 Обнаружена капча на {p_meta['name']}. Решена через 2Captcha!")
                    update_job_status(job_state, self.status_file)

            # Accept cookies
            cookie_accept = await page.query_selector("button:has-text('Accept All'), button:has-text('Accept all'), button:has-text('Allow all'), button:has-text('I agree')")
            if cookie_accept:
                try:
                    await cookie_accept.click()
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

            shot_file = f"{self.profile}_{p_id}_screen.png"
            shot_path = SCREENSHOTS_DIR / shot_file
            await page.screenshot(path=str(shot_path))
            res["screenshot"] = shot_file

            curr_url = page.url
            if any(k in curr_url.lower() for k in ["login", "signin", "sign_in", "auth"]):
                g_btn = await page.query_selector("button:has-text('Google'), a:has-text('Google'), button:has-text('GOOGLE'), button[aria-label*='Google'], button[data-provider='google']")
                if g_btn:
                    if job_state:
                        job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] 👉 Нажатие кнопки Google SSO на {p_meta['name']}...")
                        update_job_status(job_state, self.status_file)
                    await g_btn.click()
                    await page.wait_for_timeout(4000)
                    
                    # Handle Google Account chooser
                    if "accounts.google.com" in page.url:
                        acc_target = self.target_email
                        acc_el = await page.query_selector(f"div[data-identifier='{acc_target}'], div:has-text('{acc_target}')")
                        if acc_el:
                            await acc_el.click()
                            await page.wait_for_timeout(4000)
                        
                        cont_btn = await page.query_selector("button:has-text('Continue'), button:has-text('Allow'), button:has-text('Confirm'), button:has-text('Продолжить')")
                        if cont_btn:
                            await cont_btn.click()
                            await page.wait_for_timeout(4000)

                    await page.screenshot(path=str(shot_path))

            curr_url = page.url
            if not any(k in curr_url.lower() for k in ["login", "signin", "challenge", "auth0"]):
                create_btn = await page.query_selector("button:has-text('Create API key'), button:has-text('Create new key'), button:has-text('Create Key'), button:has-text('Create API Key'), button:has-text('Create token')")
                if create_btn:
                    await create_btn.click()
                    await page.wait_for_timeout(2000)
                    name_in = await page.query_selector("input[type='text'], input[placeholder*='name' i]")
                    if name_in:
                        await name_in.fill(f"AIOS-{self.tag}")
                    sub_btn = await page.query_selector("button[type='submit'], button:has-text('Create'), button:has-text('Save'), button:has-text('Submit')")
                    if sub_btn:
                        await sub_btn.click()
                        await page.wait_for_timeout(3000)

                key_elements = await page.query_selector_all("code, pre, input[readonly], [data-clipboard-text], span[class*='mono']")
                for el in key_elements:
                    val = (await el.inner_text()).strip() or (await el.get_attribute("value") or "").strip()
                    if len(val) >= 20 and " " not in val:
                        save_secret_key(p_meta["env_var"], val, self.tag)
                        res["status"] = "success"
                        res["key"] = f"{val[:6]}...{val[-4:]}"
                        if job_state:
                            job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] 🎉 [{self.tag}] Успешно получен и сохранен ключ для {p_meta['name']}: {res['key']}")
                            update_job_status(job_state, self.status_file)
                        break

                if res["status"] != "success":
                    res["status"] = "active_dashboard_opened"
                    if job_state:
                        job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] ℹ️ Дашборд {p_meta['name']} открыт. Скриншот: {shot_file}")
                        update_job_status(job_state, self.status_file)
            else:
                res["status"] = "needs_auth_or_2fa"
                res["message"] = f"Требуется подтверждение на noVNC (порт {self.novnc_port}): {curr_url[:60]}"
                if job_state:
                    job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] ⚠️ [{self.tag}] {p_meta['name']} ожидает подтверждения 2FA/Password в noVNC (:{self.novnc_port})")
                    update_job_status(job_state, self.status_file)
        except Exception as e:
            res["status"] = "error"
            res["error"] = str(e)
            if job_state:
                job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] ❌ Ошибка {p_meta['name']}: {e}")
                update_job_status(job_state, self.status_file)
        finally:
            await page.close()
            
        return res

    async def run_full_cycle(self, target_id: Optional[str] = None):
        c_bal = captcha_solver.get_balance() if captcha_solver else 0.0
        job_state = {
            "state": "running",
            "profile": self.profile,
            "progress": 0,
            "current": None,
            "google_account": self.target_email,
            "captcha_balance": c_bal,
            "novnc_port": self.novnc_port,
            "novnc_url": self.novnc_url,
            "logs": [f"[{time.strftime('%H:%M:%S')}] 🚀 Запуск Vision-RPA робота для профиля [{self.profile.upper()}] ({self.target_email}, noVNC :{self.novnc_port})..."],
            "results": []
        }
        update_job_status(job_state, self.status_file)

        await self.connect()
        
        targets = [p for p in SUPPORTED_PROVIDERS if not target_id or p["id"] == target_id]
        total = len(targets)
        
        for idx, p in enumerate(targets):
            job_state["progress"] = int((idx / total) * 100)
            job_state["current"] = p["name"]
            update_job_status(job_state, self.status_file)
            
            res = await self.provision_single(p, job_state)
            job_state["results"].append(res)
            update_job_status(job_state, self.status_file)

        notify_llmbalancer_reload()
        job_state["progress"] = 100
        job_state["state"] = "completed"
        job_state["current"] = "Готово"
        job_state["logs"].append(f"[{time.strftime('%H:%M:%S')}] ✅ Цикл RPA для профиля [{self.profile.upper()}] завершен. Балансировщик обновлен!")
        update_job_status(job_state, self.status_file)

def get_status_overview(profile: str = "primary") -> Dict[str, Any]:
    secrets = load_current_secrets()
    cfg = PROFILE_CONFIGS.get(profile, PROFILE_CONFIGS["primary"])
    status_list = []
    
    for p in SUPPORTED_PROVIDERS:
        v = secrets.get(p["env_var"], "")
        tag_v = secrets.get(f"{p['env_var']}_{cfg['tag']}", "")
        multi_var = f"{p['env_var']}S" if not p['env_var'].endswith("S") else p['env_var']
        multi_keys = [k.strip() for k in secrets.get(multi_var, "").split(",") if k.strip()]
        
        is_configured = bool(tag_v or v or len(multi_keys) > 0)
        shot_file = f"{profile}_{p['id']}_screen.png"
        shot_exists = (SCREENSHOTS_DIR / shot_file).exists()

        status_list.append({
            "id": p["id"],
            "name": p["name"],
            "env_var": p["env_var"],
            "url": p["url"],
            "models": p["models"],
            "configured": is_configured,
            "key_count": max(len(multi_keys), 1 if v else 0),
            "key_preview": f"{tag_v[:6]}...{tag_v[-4:]}" if len(tag_v) > 10 else (f"{v[:6]}...{v[-4:]}" if len(v) > 10 else ("Configured" if v else "Not Set")),
            "screenshot": shot_file if shot_exists else None
        })

    c_bal = captcha_solver.get_balance() if captcha_solver else 0.0
    return {
        "status": "success",
        "profile": profile,
        "account": cfg["email"],
        "total_providers": len(SUPPORTED_PROVIDERS),
        "active_configured": sum(1 for p in status_list if p["configured"]),
        "captcha_balance": c_bal,
        "novnc_url": cfg["novnc_url"],
        "novnc_port": cfg["novnc_port"],
        "providers": status_list
    }

def main():
    parser = argparse.ArgumentParser(description="Octopus AIOS Universal Multi-Profile Key Provisioner")
    parser.add_argument("action", choices=["scan", "run-all", "run-provider", "async-start", "job-status", "import-key", "sync-llmbalancer"], help="Action")
    parser.add_argument("--profile", choices=["primary", "secondary"], default="primary", help="Profile to use")
    parser.add_argument("--cdp", help="Custom CDP URL override")
    parser.add_argument("--id", help="Provider ID for run-provider")
    parser.add_argument("--env-var", help="Env var name")
    parser.add_argument("--key", help="Key value")
    parser.add_argument("--account", help="Account tag override")
    
    args = parser.parse_args()

    if args.action == "scan":
        print(json.dumps(get_status_overview(args.profile), indent=2, ensure_ascii=False))
        return

    if args.action == "job-status":
        print(json.dumps(get_job_status(args.profile), indent=2, ensure_ascii=False))
        return

    if args.action == "import-key":
        if not args.env_var or not args.key:
            sys.exit(1)
        tag = args.account or PROFILE_CONFIGS.get(args.profile, {}).get("tag", "MANUAL")
        save_secret_key(args.env_var, args.key, tag)
        notify_llmbalancer_reload()
        print(json.dumps({"status": "imported", "env_var": args.env_var, "tag": tag}))
        return

    if args.action == "sync-llmbalancer":
        reloaded = notify_llmbalancer_reload()
        print(json.dumps({"status": "reloaded" if reloaded else "secrets_saved"}))
        return

    if args.action == "async-start":
        cmd = ["/opt/aios-venv/bin/python3", "/opt/octopus/octopus-provider-provisioner.py", "run-all", "--profile", args.profile]
        if args.id:
            cmd = ["/opt/aios-venv/bin/python3", "/opt/octopus/octopus-provider-provisioner.py", "run-provider", "--id", args.id, "--profile", args.profile]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        print(json.dumps({"status": "started", "pid": proc.pid, "profile": args.profile, "target": args.id or "all"}))
        return

    import asyncio
    provisioner = UniversalVisionProvisioner(profile=args.profile, custom_cdp=args.cdp)
    if args.action == "run-all":
        asyncio.run(provisioner.run_full_cycle())
        print(json.dumps(get_job_status(args.profile), indent=2, ensure_ascii=False))
    elif args.action == "run-provider":
        asyncio.run(provisioner.run_full_cycle(target_id=args.id))
        print(json.dumps(get_job_status(args.profile), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()

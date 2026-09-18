#!/usr/bin/env python3
"""Fail-closed CAS credential boundary and auth contract guard."""
from __future__ import annotations
import json, os, re, stat, subprocess, urllib.error, urllib.request
from pathlib import Path
from datetime import datetime, timezone

ENVF=Path('/etc/octopus/cas-api.env')
TOKENS=Path('/etc/octopus/cas_api_tokens.json')
DROPINS=Path('/etc/systemd/system/octopus-cas-api.service.d')
URL='http://127.0.0.1:9540/cas/stats'
EXPECTED={'CAS_READ_TOKEN','CAS_WRITE_TOKEN','CAS_ADMIN_TOKEN'}

def mode(path): return stat.S_IMODE(path.stat().st_mode)
def http_code(token=None, url=URL):
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token} if token else {})
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            r.read(256); return r.status
    except urllib.error.HTTPError as e: return e.code

def main():
    checks={}; errors=[]
    try:
        checks['env_file_mode_600']=ENVF.is_file() and mode(ENVF)==0o600 and ENVF.stat().st_uid==0
        checks['token_map_mode_600']=TOKENS.is_file() and mode(TOKENS)==0o600 and TOKENS.stat().st_uid==0
        vals={}
        for line in ENVF.read_text().splitlines():
            k,sep,v=line.partition('=')
            if sep and k in EXPECTED and v: vals[k]=v
        checks['three_distinct_tokens']=set(vals)==EXPECTED and len(set(vals.values()))==3
        tmap=json.loads(TOKENS.read_text())
        checks['scoped_token_map']=len(tmap)==3 and sorted(tuple(v.get('scopes',[])) for v in tmap.values())==[('read',),('read','write'),('read','write','admin')]
        inline=[]
        for p in DROPINS.glob('*.conf'):
            for line in p.read_text(errors='replace').splitlines():
                if re.match(r'^Environment=CAS_(READ|WRITE|ADMIN)_TOKEN=',line.strip()): inline.append(p.name)
        checks['no_inline_systemd_tokens']=not inline
        pid=subprocess.check_output(['systemctl','show','octopus-cas-api.service','-p','MainPID','--value'],text=True).strip()
        if not pid or pid == '0':
            checks['service_active']=False
            checks['no_tokens_in_process_env']=True
            raw=b''
        else:
            raw=Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
        names={x.split(b'=',1)[0].decode(errors='replace') for x in raw if b'=' in x}
        checks['no_tokens_in_process_env']=not (names & EXPECTED)
        checks['service_active']=subprocess.run(['systemctl','is-active','--quiet','octopus-cas-api.service']).returncode==0
        checks['loopback_listener']='127.0.0.1:9540' in subprocess.check_output(['ss','-ltn'],text=True)
        checks['unauth_denied']=http_code()==401
        checks['wrong_denied']=http_code('invalid-guard-token')==401
        checks['read_token_allowed']=http_code(vals.get('CAS_READ_TOKEN'))==200

        cf_token=Path('/etc/cloudflared/octopus-main.token')
        checks['tunnel_token_file_mode_600']=cf_token.is_file() and mode(cf_token)==0o600 and cf_token.stat().st_uid==0
        checks['named_tunnel_active']=subprocess.run(['systemctl','is-active','--quiet','cloudflared.service']).returncode==0
        cf_pid=subprocess.check_output(['systemctl','show','cloudflared.service','-p','MainPID','--value'],text=True).strip()
        cf_cmd=Path(f'/proc/{cf_pid}/cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        checks['named_tunnel_uses_token_file']='--token-file /etc/cloudflared/octopus-main.token' in cf_cmd
        checks['named_tunnel_no_inline_token']='--token ' not in cf_cmd
        unit=Path('/etc/systemd/system/cloudflared.service').read_text(errors='replace')
        checks['unit_no_inline_tunnel_token']=not re.search(r'--token\s+\S+',unit)
        listeners=subprocess.check_output(['ss','-ltn'],text=True)
        checks['gateway_loopback']='127.0.0.1:9088' in listeners
        quick_targets=[]
        for proc in Path('/proc').glob('[0-9]*/cmdline'):
            try: cmd=proc.read_bytes().replace(b'\0',b' ').decode(errors='ignore')
            except OSError: continue
            if 'cloudflared' in cmd and '--url' in cmd and re.search(r'(127\.0\.0\.1|localhost):(9540|9088)',cmd): quick_targets.append(proc.parent.name)
        checks['no_quick_tunnel_direct_to_cas']=not quick_targets
        gateway='http://127.0.0.1:9088/cas/stats'
        checks['gateway_unauth_denied']=http_code(url=gateway)==401
        checks['gateway_read_allowed']=http_code(vals.get('CAS_READ_TOKEN'),url=gateway)==200
        checks['gateway_wrong_denied']=http_code('invalid-guard-token',url=gateway)==401
    except Exception as e:
        errors.append(type(e).__name__+': '+str(e)[:200])
    ok=not errors and all(checks.values())
    out={'timestamp':datetime.now(timezone.utc).isoformat(),'ok':ok,'read_only':True,'secret_values_emitted':False,'checks':checks,'errors':errors}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if ok else 1
if __name__=='__main__': raise SystemExit(main())

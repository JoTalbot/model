# Remote Command Result

- **Command ID:** `cmd-20260905-141500-production-proxy-check`
- **Attempt ID:** `cmd-20260905-141500-production-proxy-check-attempt-20260904T225620Z-960129`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T22:56:20Z`
- **Finished:** `2026-09-04T22:56:21Z`
- **Duration:** `1s`

## Command
```bash
set -u
printf '%s\n' 'PRODUCTION_PROXY_CHECK_START'
printf 'HOST=%s\n' "$(hostname)"
printf 'NOW=%s\n' "$(date -u +%FT%TZ)"
printf 'REPO_HEAD=%s\n' "$(git -C /opt/madworld rev-parse HEAD 2>/dev/null || echo unknown)"
printf 'ORIGIN_MAIN=%s\n' "$(git -C /opt/madworld rev-parse origin/main 2>/dev/null || echo unknown)"
printf 'REPO_REMOTE=%s\n' "$(git -C /opt/madworld remote get-url origin 2>/dev/null || echo unknown)"
printf 'BRANCH=%s\n' "$(git -C /opt/madworld branch --show-current 2>/dev/null || echo unknown)"
printf '%s\n' 'RECENT_COMMITS='
git -C /opt/madworld log -8 --oneline --decorate 2>/dev/null || true
printf '%s\n' 'GIT_STATUS='
git -C /opt/madworld status --short --branch 2>/dev/null || true
printf '%s\n' 'NGINX_CONFIG_TEST='
nginx -t 2>&1 || true
printf '%s\n' 'NGINX_SERVER_NAMES='
nginx -T 2>/dev/null | awk '/server_name[[:space:]]/{print}' | head -80 || true
printf '%s\n' 'NGINX_LISTEN='
nginx -T 2>/dev/null | awk '/listen[[:space:]]/{print}' | head -80 || true
printf '%s\n' 'HTTP_HEADERS='
curl -sS -D - -o /dev/null --max-time 10 http://127.0.0.1/health 2>&1 || true
printf '%s\n' 'HTTPS_HEADERS='
curl -k -sS -D - -o /dev/null --max-time 10 https://127.0.0.1/health 2>&1 || true
printf '%s\n' 'LOCAL_HTTP_HEALTH='
curl -sS -L -D - --max-time 10 http://127.0.0.1/health 2>&1 || true
printf '%s\n' 'LOCAL_HTTP_READY='
curl -sS -L -D - --max-time 10 http://127.0.0.1/health/ready 2>&1 || true
printf '%s\n' 'DOCKER_PS='
docker compose -f /opt/madworld/docker-compose.yml ps 2>&1 || docker ps --format '{{.Names}} {{.Status}}'
printf '%s\n' 'API_PORTS='
ss -lntp 2>/dev/null | grep -E ':(80|443|8000|8090|5432|5433)\\b' || true
printf '%s\n' 'PRODUCTION_PROXY_CHECK_END'
```

## STDOUT
```text
PRODUCTION_PROXY_CHECK_START
HOST=arm-server-01
NOW=2026-09-04T22:56:20Z
REPO_HEAD=b66e1ec3afa0d3796e9a5fd4eafb5107d5d9fac5
ORIGIN_MAIN=4339091ba0077b321bdad74e199d20645cbeefc0
REPO_REMOTE=git@github.com-madworld:JoTalbot/MadWorld.git
BRANCH=main
RECENT_COMMITS=
b66e1ec (HEAD -> main) chore(remote-operator): request live server status check
db0c9de test(remote-operator): run server health audit
4d5ab0d docs(remote-operator): document agent SSH usage
baa336d docs(agents): document SSH access via remote operator
86b0548 fix(remote-operator): isolate result sync from main
845d55f chore(remote-operator): record command execution result
85605a5 chore(remote-operator): record command execution result
8398df4 fix(remote-operator): make executor queue state-aware
GIT_STATUS=
## main...origin/main [behind 13]
 M .github/remote-operator/COMMANDS.txt
 M .github/workflows/deploy-on-push.yml
 M AGENTS.md
 M docs/REMOTE_OPERATOR.md
 M docs/REMOTE_OPERATOR_INSTALL.md
?? .github/remote-operator/results/cmd-20260904-220309-operator-test/
?? .github/remote-operator/results/cmd-20260904-220600-home-tree/
?? .github/remote-operator/results/cmd-20260904-220900-operator-delivery-diagnostic/
?? .github/remote-operator/results/cmd-20260905-005600-server-status/
?? .github/remote-operator/results/cmd-20260905-135000-server-health/
?? .github/remote-operator/results/cmd-20260905-135500-disk-space/
?? .github/remote-operator/results/cmd-20260905-140000-server-status-tree/
?? .github/remote-operator/results/cmd-20260905-140500-server-runtime-final/
?? .github/remote-operator/results/cmd-20260905-141500-production-proxy-check/
?? .github/remote-operator/state/cmd-20260904-220309-operator-test.json
?? .github/remote-operator/state/cmd-20260904-220600-home-tree.json
?? .github/remote-operator/state/cmd-20260904-220900-operator-delivery-diagnostic.json
?? .github/remote-operator/state/cmd-20260905-005600-server-status.json
?? .github/remote-operator/state/cmd-20260905-135000-server-health.json
?? .github/remote-operator/state/cmd-20260905-135500-disk-space.json
?? .github/remote-operator/state/cmd-20260905-140000-server-status-tree.json
?? .github/remote-operator/state/cmd-20260905-140500-server-runtime-final.json
?? .github/remote-operator/state/cmd-20260905-141500-production-proxy-check.json
?? docs/REMOTE_OPERATOR_UNIVERSAL.md
NGINX_CONFIG_TEST=
2026/09/04 22:56:20 [warn] 960178#960178: the "user" directive makes sense only if the master process runs with super-user privileges, ignored in /etc/nginx/nginx.conf:1
2026/09/04 22:56:20 [emerg] 960178#960178: cannot load certificate key "/etc/nginx/ssl/api.autosklo.org.ua.origin.key": BIO_new_file() failed (SSL: error:8000000D:system library::Permission denied:calling fopen(/etc/nginx/ssl/api.autosklo.org.ua.origin.key, r) error:10080002:BIO routines::system lib)
nginx: configuration file /etc/nginx/nginx.conf test failed
NGINX_SERVER_NAMES=
NGINX_LISTEN=
HTTP_HEADERS=
HTTP/1.1 301 Moved Permanently
Server: nginx/1.24.0 (Ubuntu)
Date: Fri, 04 Sep 2026 22:56:20 GMT
Content-Type: text/html
Content-Length: 178
Connection: keep-alive
Location: https://127.0.0.1/health

HTTPS_HEADERS=
HTTP/1.1 200 OK
Server: nginx/1.24.0 (Ubuntu)
Date: Fri, 04 Sep 2026 22:56:20 GMT
Content-Type: application/json
Content-Length: 40
Connection: keep-alive
x-request-id: 8e665338-5ea7-4882-b17a-405f89de844e
x-content-type-options: nosniff
x-frame-options: DENY
referrer-policy: no-referrer
x-ratelimit-remaining: 119

LOCAL_HTTP_HEALTH=
HTTP/1.1 301 Moved Permanently
Server: nginx/1.24.0 (Ubuntu)
Date: Fri, 04 Sep 2026 22:56:20 GMT
Content-Type: text/html
Content-Length: 178
Connection: keep-alive
Location: https://127.0.0.1/health

curl: (60) SSL certificate problem: self-signed certificate in certificate chain
More details here: https://curl.se/docs/sslcerts.html

curl failed to verify the legitimacy of the server and therefore could not
establish a secure connection to it. To learn more about this situation and
how to fix it, please visit the web page mentioned above.
LOCAL_HTTP_READY=
HTTP/1.1 301 Moved Permanently
Server: nginx/1.24.0 (Ubuntu)
Date: Fri, 04 Sep 2026 22:56:20 GMT
Content-Type: text/html
Content-Length: 178
Connection: keep-alive
Location: https://127.0.0.1/health/ready

curl: (60) SSL certificate problem: self-signed certificate in certificate chain
More details here: https://curl.se/docs/sslcerts.html

curl failed to verify the legitimacy of the server and therefore could not
establish a secure connection to it. To learn more about this situation and
how to fix it, please visit the web page mentioned above.
DOCKER_PS=
NAME                           IMAGE                        COMMAND                  SERVICE             CREATED        STATUS                  PORTS
madworld-api-1                 madworld-api                 "uvicorn app.main:ap…"   api                 12 hours ago   Up 12 hours (healthy)   127.0.0.1:8090->8000/tcp
madworld-postgres-1            postgres:16                  "docker-entrypoint.s…"   postgres            12 hours ago   Up 12 hours (healthy)   127.0.0.1:5433->5432/tcp
madworld-world-tick-worker-1   madworld-world-tick-worker   "python -m scripts.w…"   world-tick-worker   12 hours ago   Up 12 hours             8000/tcp
API_PORTS=
PRODUCTION_PROXY_CHECK_END
```

## STDERR
```text
```

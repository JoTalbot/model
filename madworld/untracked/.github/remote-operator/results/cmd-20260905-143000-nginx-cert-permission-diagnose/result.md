# Remote Command Result

- **Command ID:** `cmd-20260905-143000-nginx-cert-permission-diagnose`
- **Attempt ID:** `cmd-20260905-143000-nginx-cert-permission-diagnose-attempt-20260904T225827Z-966502`
- **Status:** `DONE`
- **Exit code:** `0`
- **Executor:** `arm-server-01`
- **Started:** `2026-09-04T22:58:27Z`
- **Finished:** `2026-09-04T22:58:28Z`
- **Duration:** `1s`

## Command
```bash
set -u
printf '%s\n' 'NGINX_CERT_PERMISSION_DIAGNOSE_START'
printf 'HOST=%s\n' "$(hostname)"
printf '%s\n' 'CERT_FILES='
find /etc/nginx/ssl -maxdepth 1 -type f -printf '%M %u:%g %p\\n' 2>/dev/null | sort || true
printf '%s\n' 'NGINX_USER_CONFIG='
awk '/^[[:space:]]*user[[:space:]]/{print}' /etc/nginx/nginx.conf 2>/dev/null || true
printf '%s\n' 'CERT_PATHS='
grep -RInE 'ssl_certificate(_key)?[[:space:]]+' /etc/nginx 2>/dev/null | head -80 || true
printf '%s\n' 'SERVICE_USER='
ps -eo user,group,pid,comm,args | grep '[n]ginx' | head -20 || true
printf '%s\n' 'PARENT_DIR_PERMS='
namei -l /etc/nginx/ssl/api.autosklo.org.ua.origin.key 2>&1 || true
printf '%s\n' 'NGINX_TEST='
nginx -t 2>&1 || true
printf '%s\n' 'NGINX_CERT_PERMISSION_DIAGNOSE_END'
```

## STDOUT
```text
NGINX_CERT_PERMISSION_DIAGNOSE_START
HOST=arm-server-01
CERT_FILES=
-rw-r--r-- root:root /etc/nginx/ssl/cloudflare_origin_ca_rsa.pem\n-rw------- root:root /etc/nginx/ssl/api.autosklo.org.ua.key\n-rw-r--r-- root:root /etc/nginx/ssl/api.autosklo.org.ua.origin.fullchain.pem\n-rw------- root:root /etc/nginx/ssl/api.autosklo.org.ua.origin.key\n-rw-r--r-- root:root /etc/nginx/ssl/api.autosklo.org.ua.fullchain.pem\n-rw-r--r-- root:root /etc/nginx/ssl/api.autosklo.org.ua.origin.pem\n
NGINX_USER_CONFIG=
user www-data;
CERT_PATHS=
/etc/nginx/snippets/snakeoil.conf:4:ssl_certificate /etc/ssl/certs/ssl-cert-snakeoil.pem;
/etc/nginx/snippets/snakeoil.conf:5:ssl_certificate_key /etc/ssl/private/ssl-cert-snakeoil.key;
/etc/nginx/sites-available/api.autosklo.org.ua:33:    ssl_certificate     /etc/nginx/ssl/api.autosklo.org.ua.origin.fullchain.pem;
/etc/nginx/sites-available/api.autosklo.org.ua:34:    ssl_certificate_key /etc/nginx/ssl/api.autosklo.org.ua.origin.key;
/etc/nginx/sites-enabled/api.autosklo.org.ua:33:    ssl_certificate     /etc/nginx/ssl/api.autosklo.org.ua.origin.fullchain.pem;
/etc/nginx/sites-enabled/api.autosklo.org.ua:34:    ssl_certificate_key /etc/nginx/ssl/api.autosklo.org.ua.origin.key;
SERVICE_USER=
ubuntu   ubuntu    966527 bash            bash /opt/madworld/.github/remote-operator/results/cmd-20260905-143000-nginx-cert-permission-diagnose/cmd-20260905-143000-nginx-cert-permission-diagnose-attempt-20260904T225827Z-966502/command.sh
ubuntu   ubuntu    966528 bash            bash /opt/madworld/ops/remote-operator/state-manager.sh transition /opt/madworld/.github/remote-operator/state/cmd-20260905-143000-nginx-cert-permission-diagnose.json RUNNING RUNNING {"pid":966527}
ubuntu   ubuntu    966536 python3         python3 - /opt/madworld/.github/remote-operator/state/cmd-20260905-143000-nginx-cert-permission-diagnose.json RUNNING RUNNING {"pid":966527}
root     root     2595191 nginx           nginx: master process /usr/sbin/nginx -g daemon on; master_process on;
www-data www-data 2602583 nginx           nginx: worker process
www-data www-data 2602585 nginx           nginx: worker process
www-data www-data 2602586 nginx           nginx: worker process
www-data www-data 2602587 nginx           nginx: worker process
PARENT_DIR_PERMS=
f: /etc/nginx/ssl/api.autosklo.org.ua.origin.key
drwxr-xr-x root root /
drwxr-xr-x root root etc
drwxr-xr-x root root nginx
drwxr-xr-x root root ssl
-rw------- root root api.autosklo.org.ua.origin.key
NGINX_TEST=
2026/09/04 22:58:27 [warn] 966544#966544: the "user" directive makes sense only if the master process runs with super-user privileges, ignored in /etc/nginx/nginx.conf:1
2026/09/04 22:58:27 [emerg] 966544#966544: cannot load certificate key "/etc/nginx/ssl/api.autosklo.org.ua.origin.key": BIO_new_file() failed (SSL: error:8000000D:system library::Permission denied:calling fopen(/etc/nginx/ssl/api.autosklo.org.ua.origin.key, r) error:10080002:BIO routines::system lib)
nginx: configuration file /etc/nginx/nginx.conf test failed
NGINX_CERT_PERMISSION_DIAGNOSE_END
```

## STDERR
```text
```

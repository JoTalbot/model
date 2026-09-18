# Arena/Gemini health runbook

Статус: включено в production guard.

Основной health report:
/root/agents/-Octopus/tools/octopus-arena-health-report.py

Production guard теперь включает секцию:
## arena_gemini_port

Проверяется:
- наличие prompt/workflow/tool файлов;
- spool queue размеры и counts;
- octopus-arena-spool-worker.timer enabled/active;
- octopus-arena-spool-hygiene.timer enabled/active;
- firewall service enabled/active;
- blind execution disabled;
- SSH execution gate: validator + exact approval;
- browser live gate: OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1.

Быстрая проверка:
/root/agents/-Octopus/tools/octopus-arena-health-report.py
/usr/local/sbin/octopus-production-guard-report /var/tmp/octopus-production-guard-report.out

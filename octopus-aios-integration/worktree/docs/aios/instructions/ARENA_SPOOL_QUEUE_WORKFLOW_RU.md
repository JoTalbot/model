# Arena/Gemini spool queue workflow

Статус: production-ready guarded queue.

Spool root:
/var/spool/octopus-arena-agent

Папки:
- incoming/ — левый ответ Arena/Gemini для validator dry-run.
- validated/ — прошедшие validator команды.
- approved/ — команды для выполнения, только с sidecar .approval.
- outbox/ — stdout/stderr после выполнения, материал для pasteback в Arena.
- rejected/ — заблокированные/ошибочные команды.
- logs/ — отчёты worker.

Dry-run validate:
  cp /var/tmp/octopus-arena-left-answer.txt /var/spool/octopus-arena-agent/incoming/task.txt
  systemctl start octopus-arena-spool-worker.service

Approved execute:
  cp /var/tmp/octopus-arena-left-answer.txt /var/spool/octopus-arena-agent/approved/task.txt
  printf 'РАЗРЕШАЮ ВЫПОЛНИТЬ SSH КОМАНДУ\n' > /var/spool/octopus-arena-agent/approved/task.approval
  systemctl start octopus-arena-spool-worker.service

Pasteback stdout:
  OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1 /root/agents/-Octopus/tools/octopus-arena-stdout-pasteback.py --stdout-file /var/spool/octopus-arena-agent/outbox/<file>.stdout

Timer:
  octopus-arena-spool-worker.timer — every minute.

Blind AI -> SSH execution отключён. Validator и approval sidecar обязательны.

# Arena/Gemini spool hygiene policy

Статус: включено.

Scope: /var/spool/octopus-arena-agent only.

Retention:
- validated: archive/delete after 24h;
- rejected: archive/delete after 24h;
- outbox: archive/delete after 48h;
- logs: keep latest 200;
- size cap target: 100MB.

Protected:
- incoming/ не чистится автоматически;
- approved/ не чистится автоматически, чтобы не потерять ожидающую approval задачу.

Timer:
- octopus-arena-spool-hygiene.timer — daily.

Blind AI execution не включается.

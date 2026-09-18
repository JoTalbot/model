# Gemini/Arena final acceptance manifest

Компоненты:
- prompt contract: GEMINI_ARENA_SYSTEM_PROMPT_RU.md
- browser controller: octopus-arena-browser-controller.py
- live smoke helper: octopus-arena-live-smoke.py
- SSH bridge validator: octopus-gemini-ssh-bridge.py
- agent loop: octopus-arena-agent-loop.py
- stdout pasteback: octopus-arena-stdout-pasteback.py
- approved full loop: octopus-arena-approved-full-loop.py
- spool worker: octopus-arena-spool-worker.py
- spool hygiene: octopus-arena-spool-hygiene.py
- health report: octopus-arena-health-report.py

Acceptance rules:
- внешний AI не выполняется вслепую;
- browser live action требует OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1;
- SSH/terminal execution требует validator + exact approval phrase;
- опасные команды блокируются validator;
- stdout после выполнения идёт в outbox/pasteback;
- production guard видит arena_gemini_port;
- spool worker и hygiene timers active;
- SLO green, failed units 0, r3_verify success.

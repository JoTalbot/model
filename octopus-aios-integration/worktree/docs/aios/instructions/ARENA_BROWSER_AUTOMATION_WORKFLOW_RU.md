# Arena browser automation workflow

Статус: guarded browser I/O only.

1. Проверить dry-run:
   /root/agents/-Octopus/tools/octopus-arena-browser-controller.py --dry-run

2. Пост prompt в arena.ai только после ручного разрешения env:
   OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1 /root/agents/-Octopus/tools/octopus-arena-browser-controller.py --post-prompt

3. Забрать левый ответ и прогнать validator dry-run:
   OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1 /root/agents/-Octopus/tools/octopus-arena-browser-controller.py --extract-left-answer --validate-left-answer --out /var/tmp/octopus-arena-left-answer.txt

4. Выполнить SSH/terminal-команду только отдельной командой и approval:
   /root/agents/-Octopus/tools/octopus-arena-agent-loop.py --answer-file /var/tmp/octopus-arena-left-answer.txt --execute --approval 'РАЗРЕШАЮ ВЫПОЛНИТЬ SSH КОМАНДУ'

5. Stdout для вставки обратно в Arena лежит в pasteback_file из RESULT.json.

Слепая цепочка browser -> AI -> SSH execute отключена.

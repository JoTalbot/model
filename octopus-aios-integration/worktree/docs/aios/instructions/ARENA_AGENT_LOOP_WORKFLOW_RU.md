# Arena/Gemini agent loop workflow

Статус: controlled-auto, не blind-auto.

1. Напечатать prompt для вставки в Arena:
   /root/agents/-Octopus/tools/octopus-arena-agent-loop.py --print-prompt

2. В Arena выбрать левый вариант ответа.

3. Сохранить левый ответ в файл, например:
   /var/tmp/octopus-arena-left-answer.txt

4. Dry-run validator:
   /root/agents/-Octopus/tools/octopus-arena-agent-loop.py --answer-file /var/tmp/octopus-arena-left-answer.txt

5. Выполнить только после явного разрешения:
   /root/agents/-Octopus/tools/octopus-arena-agent-loop.py --answer-file /var/tmp/octopus-arena-left-answer.txt --execute --approval 'РАЗРЕШАЮ ВЫПОЛНИТЬ SSH КОМАНДУ'

6. Stdout для вставки обратно в Arena будет в pasteback_file из RESULT.json.

7. Browser automation template есть, но требует уже установленный Playwright и env:
   OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1

Blind external AI execution отключён.

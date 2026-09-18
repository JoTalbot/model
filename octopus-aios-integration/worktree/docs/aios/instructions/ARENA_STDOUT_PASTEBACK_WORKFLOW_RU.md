# Arena stdout pasteback workflow

Статус: готово, guarded.

1. Левый ответ Arena/Gemini сохранить в файл:
   /var/tmp/octopus-arena-left-answer.txt

2. Dry-run всего цикла без SSH execute:
   /root/agents/-Octopus/tools/octopus-arena-approved-full-loop.py --answer-file /var/tmp/octopus-arena-left-answer.txt --pasteback-dry-run

3. Выполнение terminal/SSH-команды только с approval:
   /root/agents/-Octopus/tools/octopus-arena-approved-full-loop.py --answer-file /var/tmp/octopus-arena-left-answer.txt --execute --approval 'РАЗРЕШАЮ ВЫПОЛНИТЬ SSH КОМАНДУ' --pasteback-dry-run

4. Живой pasteback stdout в браузер Arena только после env-разрешения:
   OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1 /root/agents/-Octopus/tools/octopus-arena-stdout-pasteback.py --stdout-file <PASTEBACK_FILE>

5. Живой pasteback+submit:
   OCTOPUS_ALLOW_BROWSER_AI_BRIDGE=1 /root/agents/-Octopus/tools/octopus-arena-stdout-pasteback.py --stdout-file <PASTEBACK_FILE> --submit

Blind AI -> SSH execute отключён. Validator и approval обязательны.

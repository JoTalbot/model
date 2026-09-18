# Post-success wave-run compaction policy

Пользователь разрешил и поручил: после успешного выполнения крупных wave-run выполнять archive-verified compaction apply-gate.

Обязательная последовательность:
1. Проверить /system/status.
2. Если disk > 90%, вызвать /system/cleanup.
3. После успешного smoke/summary wave-run определить run directory.
4. Найти только strict ITER-файлы: `ITER_[0-9]{2,3}.md`.
5. Создать tar.gz архив ITER-файлов.
6. Посчитать SHA256 архива.
7. Выполнить restore-smoke sample-файла и сравнить SHA256.
8. Только после успешной проверки удалить исходные ITER-файлы из exact run directory.
9. Оставить `ITER_FILES_ARCHIVED.md` marker.
10. Запустить r3_verify и обновить launch board/action ledger.

Запрещено: удалять SUMMARY/SMOKE/STATUS/MANIFEST/board, менять DNS/Cloudflare/firewall/nginx/core services без отдельного gate.

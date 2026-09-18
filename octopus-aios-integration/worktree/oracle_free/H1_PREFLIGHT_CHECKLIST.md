# H1 — Oracle Always Free pre-flight checklist
Дата: 2026-06-19

## Что от тебя нужно (один раз)
1. **Регистрация на Oracle Cloud** (если ещё нет):
   - https://www.oracle.com/cloud/free/
   - ⚠️ При регистрации требуется кредитная карта для верификации.
     По #09 это формально не «бесплатно по умолчанию», поэтому ты должен
     явно подтвердить, что готов использовать этот аккаунт.
   - Регион выбрать: **eu-frankfurt-1** (близко к Hetzner) или **eu-stockholm-1**.

2. **Создать API user + ключи** в OCI Console:
   - Identity → Users → Create User (octopus-agent)
   - Tokens & Keys → Add API Key → Generate (скачать private key .pem)
   - Полиси: "Allow group <grp> to manage all-resources in compartment <id>"

3. **Прислать в защищённом канале (TG, не в этом чате):**
   - tenancy_ocid (ocid1.tenancy.oc1..xxx)
   - user_ocid (ocid1.user.oc1..xxx)
   - fingerprint (xx:xx:xx:...)
   - private_key.pem (содержимое)
   - compartment_ocid (можно tenancy_ocid для root)

4. **Подтвердить лимит** в OCI Console:
   - Governance → Limits → Always Free shapes → должно быть >0 для VM.Standard.A1.Flex

## Что я сделаю автоматически после получения credentials
1. Сохраню creds в `/etc/octopus/oracle.env` (0600, root only).
2. Установлю terraform (apt install terraform или snap).
3. Сделаю `terraform init && terraform plan` — покажу тебе план перед apply.
4. **С твоим явным «да, делай apply»** запущу `terraform apply` — создание VM (1 OCPU, 6GB, 50GB).
5. VM при первом boot подтянет eternal-snapshot и присоединится к рою через reverse tunnel порт 9923.
6. Добавлю в `mesh_nodes.json` запись `oracle-free-arm-1`.
7. Через 10 минут проверю что нода появилась в `octopus health` и `octopus_swarm_online` увеличился на 1.

## Откат (если что-то пошло не так)
- `terraform destroy` — удалит VM (биллинг не пострадает, т.к. free-tier).
- Запись из mesh_nodes.json удалится.
- Никаких изменений на parent не остаётся.

## Связь с инструкциями
- #08: явное подтверждение пользователя — будет на шаге 4.
- #09: free-tier с картой — нужно твоё «да» (это шаг 0).
- #13: каждый этап (init, plan, apply) — отдельная команда с verify.
- #19: новая нода автоматически попадает в multisync.
- #20: при падении ноды autoheal зафиксирует.

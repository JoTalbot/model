# ULTRA DEEP RESEARCH: development-mode (Octopus Dynamic Tools)
**Дата:** 2026-06-19
**Проблема, которую решает:** Во время активной разработки проекта абсолютно не нужны запущенные тяжёлые модели, whisper workers, vector search и т.д. Они жрут ресурсы бесплатных нод впустую.

**Решение:** 
- development-mode-guard + development-mode — удобный триггер "включи режим разработки"
- dynamic-tool-orchestrator — мозг, который принимает решение
- script-deployer — исполнитель (start/stop/install/uninstall)
- resource-demand-evaluator — оценивает текущую необходимость
- tool-desired-state — хранит желаемое состояние

**Аналоги в продакшене:**
- Kubernetes "dev mode" / profiles
- Docker Compose profiles
- Nomad / Terraform dynamic scaling
- Serverless cold-start логика

**Интеграция с существующими скиллами:**
- consent-orchestrator (обязательно)
- free-tier-orchestrator
- self-healing-swarm
- capability-registry
- load-aware-scheduler

**Пример использования:**
Пользователь говорит: "сейчас идёт разработка проекта и абсолютно не нужны запущенные скрипты, модели"
→ development-mode активируется
→ динамически останавливаются все ненужные процессы
→ ресурсы освобождаются
→ при необходимости одним сообщением возвращается в production mode

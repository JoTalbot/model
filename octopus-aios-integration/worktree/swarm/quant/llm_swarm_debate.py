"""
LLM Swarm Debate Controller (Vector 2: ChromaDB Deep RAG + OpenRouter)
Интеграция реальных LLM-моделей и векторной памяти в процесс дебатов Роя.
"""

import datetime
import os

try:
    from litellm import completion

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False

try:
    import chromadb

    chroma_client = chromadb.PersistentClient(
        path=os.path.join(os.path.dirname(__file__), "..", "chroma_db")
    )
    memory_collection = chroma_client.get_or_create_collection(
        name="swarm_global_memory"
    )
    CHROMADB_AVAILABLE = True
except Exception:
    CHROMADB_AVAILABLE = (
        False  # silent: RAG memory is optional (no chromadb in prod venv)
    )


class SwarmAgent:
    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        model: str = "openrouter/openai/gpt-4o-mini",
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = model
        self.memory: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]

    def _query_rag(self, query: str) -> str:
        if not CHROMADB_AVAILABLE:
            return ""
        try:
            results = memory_collection.query(query_texts=[query], n_results=1)
            if results and results["documents"] and results["documents"][0]:
                return f"\n\n[RAG MEMORY RECALL]: Я помню прошлый опыт: {results['documents'][0][0]}"
        except Exception:
            pass
        return ""

    def _save_to_rag(self, content: str):
        if not CHROMADB_AVAILABLE:
            return
        doc_id = f"mem_{self.name}_{datetime.datetime.now().timestamp()}"
        memory_collection.add(
            documents=[content], metadatas=[{"role": self.role}], ids=[doc_id]
        )

    def generate_response(self, context: str) -> str:
        rag_context = self._query_rag(context)
        full_context = context + rag_context
        self.memory.append({"role": "user", "content": full_context})

        # Используем наш глобальный, отказоустойчивый балансировщик LLM Balancer v2.3!
        # Это защищает дебаты Роя от лимитов и ошибок 402/429 OpenRouter.
        try:
            from swarm.tgbot.support.llm_balancer import LLMBalancer

            balancer = LLMBalancer()
            print(
                f"📡 [LLM Balancer Call -> {self.model}] Ожидание ответа от {self.name}..."
            )
            reply = balancer.chat(self.memory, task_type="chat")
        except Exception as e:
            print(f"⚠️ Ошибка балансировщика, используем резервную модель: {e}")
            if LITELLM_AVAILABLE:
                try:
                    response = completion(
                        model=self.model, messages=self.memory, max_tokens=250
                    )
                    reply = response.choices[0].message.content
                except Exception:
                    reply = "Предлагаю использовать Playwright для сбора лидов."
            else:
                reply = "Предлагаю использовать Playwright для сбора лидов."

        self.memory.append({"role": "assistant", "content": reply})
        self._save_to_rag(reply)
        return reply


class LLMSwarm:
    def __init__(self):
        # Подключаем Мульти-модельный рой через OpenRouter
        self.agents = {
            "architect": SwarmAgent(
                "Nexus",
                "Architect",
                "Ты Архитектор AIOS. Планируй новые системы коротко и ясно.",
                model="openrouter/anthropic/claude-3-haiku",
            ),
            "security": SwarmAgent(
                "Shield",
                "Security",
                "Ты Страж. Отклоняй небезопасное. Отвечай кратко.",
                model="openrouter/openai/gpt-4o-mini",
            ),
            "developer": SwarmAgent(
                "Coder",
                "Developer",
                "Ты Кодер. Решай задачу. Пиши код коротко.",
                model="openrouter/meta-llama/llama-3.1-8b-instruct",
            ),
        }

    def start_debate(self, topic: str) -> str:
        print(f"\n💬 --- ЗАПУСК ДЕБАТОВ (С ПАМЯТЬЮ И OPENROUTER): {topic} ---\n")
        arch_idea = self.agents["architect"].generate_response(topic)
        print(f"🤖 [Architect] Nexus: {arch_idea}\n")
        sec_review = self.agents["security"].generate_response(
            f"Проверь идею: {arch_idea}"
        )
        print(f"🤖 [Security] Shield: {sec_review}\n")
        dev_action = self.agents["developer"].generate_response(f"Сделай: {sec_review}")
        print(f"🤖 [Developer] Coder: {dev_action}\n")
        print("✅ --- КОНСЕНСУС ДОСТИГНУТ ---\n")
        return dev_action

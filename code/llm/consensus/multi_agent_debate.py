"""AIOS Multi-Agent Consensus Debate Engine.
Orchestrates multi-model deliberation across 4 distinct AI tiers:
- Proponent (Thesis): Ultra-Fast Edge Tier (Groq LPU / Cerebras)
- Critic (Antithesis): Deep Reasoning Tier (Groq GPT-OSS-120B / SambaNova 405B)
- Synthesizer (Code & Plan): Code Tier (Mistral AI / HF Qwen 72B)
- Arbiter (Consensus Verdict): Long-Context Tier (Google Gemini 2.5 Flash)
Automatically persists consensus decisions into the Knowledge Fabric long-term memory.
"""
import sys, time, json, asyncio
from typing import Dict, Any, Optional

try:
    from aios.llm.llm_balancer import LLMBalancer
    from aios.memory_fabric.knowledge_graph import KnowledgeFabric
except ImportError:
    from llm.llm_balancer import LLMBalancer
    from memory_fabric.knowledge_graph import KnowledgeFabric

class MultiAgentDebateEngine:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.balancer = LLMBalancer.get_instance()
        self.knowledge_fabric = KnowledgeFabric.get_instance()

    async def conduct_debate(self, topic: str, max_rounds: int = 1) -> Dict[str, Any]:
        t0 = time.time()
        print(f"🏛️ Starting Multi-Agent Debate on: '{topic}'")

        # 1. Round 1: Thesis (Proponent)
        prompt_thesis = f"Ты — Главный Архитектор системы. Выдвинь четкий тезис и предложение решения по теме: '{topic}'. Сформулируй 3 конкретных аргумента 'ЗА' с акцентом на скорость и эффективность."
        thesis_res = await self.balancer.ask(prompt_thesis, task_type="fast", use_cache=False)
        thesis_text = thesis_res.get("text", "")

        # 2. Round 2: Antithesis (Critic)
        prompt_antithesis = f"""Ты — Главный Аудитор по надежности и безопасности. 
Проанализируй предложение Архитектора и тему: '{topic}'.
Предложение Архитектора:
{thesis_text}

Сформулируй 3 жестких контраргумента 'ПРОТИВ', выдели потенциальные уязвимости, скрытые риски и узкие места производительности."""
        antithesis_res = await self.balancer.ask(prompt_antithesis, task_type="reasoning", use_cache=False)
        antithesis_text = antithesis_res.get("text", "")

        # 3. Round 3: Synthesis (Engineer / Code Synthesizer)
        prompt_synthesis = f"""Ты — Ведущий Системный Инженер. 
Синтезируй конструктивные позиции Архитектора и Аудитора по теме '{topic}'.
Тезис Архитектора:
{thesis_text}

Критика Аудитора:
{antithesis_text}

Сформируй компромиссный план реализации, устраняющий выявленные риски."""
        synthesis_res = await self.balancer.ask(prompt_synthesis, task_type="code", use_cache=False)
        synthesis_text = synthesis_res.get("text", "")

        # 4. Round 4: Judge / Consensus Verdict
        prompt_judge = f"""Ты — Верховный Арбитр распределенного ИИ-кластера.
Внимательно изучи позиции всех сторон по вопросу: '{topic}'

1. Архитектор (Тезис):
{thesis_text}

2. Аудитор (Антитезис):
{antithesis_text}

3. Инженер (Синтез):
{synthesis_text}

Вынеси окончательный консенсусный вердикт кластера:
- Итоговое решение (1-2 абзаца)
- Ключевые компромиссы
- Оценка надежности решения (в % от 0 до 100)"""
        judge_res = await self.balancer.ask(prompt_judge, task_type="long_context", use_cache=False)
        judge_text = judge_res.get("text", "")

        total_time_ms = round((time.time() - t0) * 1000, 1)

        result = {
            "topic": topic,
            "total_time_ms": total_time_ms,
            "participants": {
                "proponent": {"model": thesis_res.get("provider"), "tier": "fast", "text": thesis_text},
                "critic": {"model": antithesis_res.get("provider"), "tier": "reasoning", "text": antithesis_text},
                "synthesizer": {"model": synthesis_res.get("provider"), "tier": "code", "text": synthesis_text},
                "arbiter": {"model": judge_res.get("provider"), "tier": "long_context", "text": judge_text}
            },
            "consensus_verdict": judge_text
        }

        # Persist decision to Knowledge Fabric
        try:
            ep_id = self.knowledge_fabric.record_episode(
                title=f"Консилиум: {topic[:80]}",
                content=f"Тема дебатов: {topic}\nВердикт: {judge_text}\nСинтез: {synthesis_text[:500]}",
                metadata={"type": "multi_agent_debate", "time_ms": total_time_ms}
            )
            result["knowledge_episode_id"] = ep_id
        except Exception as e:
            result["knowledge_error"] = str(e)

        return result

    def conduct_debate_sync(self, topic: str) -> Dict[str, Any]:
        try:
            return asyncio.run(self.conduct_debate(topic))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.conduct_debate(topic))
            finally:
                loop.close()

debate_engine = MultiAgentDebateEngine.get_instance()

if __name__ == "__main__":
    t = "Хранить ли сессионные данные агентов в Redis или напрямую в PostgreSQL pgvector?"
    res = debate_engine.conduct_debate_sync(t)
    print("\n" + "="*60)
    print("🏛️ ДЕБАТЫ ЗАВЕРШЕНЫ:")
    print("="*60)
    print(f"Время: {res['total_time_ms']} ms")
    print(f"Арбитр ({res['participants']['arbiter']['model']}):")
    print(res['consensus_verdict'])

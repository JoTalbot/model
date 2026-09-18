from __future__ import annotations

import json
import logging

from swarm.agent.core import Task

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """You are a task decomposition engine. Break the following task into smaller independent subtasks.
Return a JSON array of strings, each string is a subtask description.
Example: ["subtask 1", "subtask 2", "subtask 3"]

Task: {description}

Return ONLY the JSON array, nothing else."""


class TaskManager:
    def __init__(self, llm, node_id: str) -> None:
        self.llm = llm
        self.node_id = node_id

    async def decompose(self, task: Task) -> list[Task]:
        prompt = DECOMPOSE_PROMPT.format(description=task.description)
        raw = await self.llm.complete([{"role": "user", "content": prompt}])

        try:
            descriptions = json.loads(raw)
            if not isinstance(descriptions, list):
                raise ValueError("Expected a list")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("LLM returned invalid JSON for decomposition: %s", exc)
            return [Task(description=task.description, creator_id=self.node_id)]

        return [
            Task(description=desc, creator_id=self.node_id)
            for desc in descriptions
        ]

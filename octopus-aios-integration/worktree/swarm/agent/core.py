from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from swarm.agent.executor import TaskExecutor
from swarm.agent.reasoning import ReasoningEngine
from swarm.agent.repair import RepairLoop
from swarm.events.events import TaskCreated
from swarm.network.gossip import GossipProtocol, GossipMessage

logger = logging.getLogger(__name__)

class TaskStatus(enum.Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    description: str
    creator_id: str
    creator_address: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None
    result: str | None = None
    subtasks: list[Task] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "creator_id": self.creator_id,
            "creator_address": self.creator_address,
            "status": self.status.value,
            "assigned_to": self.assigned_to,
            "result": self.result,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        import uuid, time
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            description=data["description"],
            creator_id=data.get("creator_id", ""),
            creator_address=data.get("creator_address"),
            status=TaskStatus(data.get("status", "pending")),
            assigned_to=data.get("assigned_to"),
            result=data.get("result"),
            created_at=data.get("created_at", 0.0),
        )


class SwarmAgent:
    def __init__(
        self,
        node_id,
        memory,
        llm,
        gossip,
        rpc_client,
        memory_port=None,
        graph_rag=None,
        reputation=None,
        *,
        repair_interval_seconds: int = 0,
        bus=None,
    ):
        self.node_id = node_id
        self.memory = memory
        self.memory_port = memory_port
        self.llm = llm
        self.gossip = gossip
        self.rpc_client = rpc_client
        self.bus = bus
        self.graph_rag = graph_rag
        self.reputation = reputation
        self.reasoning = ReasoningEngine(llm, getattr(self, "graph_rag", None))
        self.executor = TaskExecutor(
            node_id=node_id,
            memory=memory,
            reasoning=self.reasoning,
            memory_port=memory_port,
            bus=bus,
        )
        self.repair_loop = RepairLoop(memory, repair_interval_seconds, bus=bus)
        self.skills: dict[str, Callable] = {}
        self.task_queue: asyncio.Queue[Task] = asyncio.Queue()

        # Distributed Task Pool
        self.pool: dict[str, Task] = {}

        self._running = False
        self._loop_task: asyncio.Task | None = None

    def register_skill(self, name, handler):
        self.skills[name] = handler

    async def think(self, context, system_prompt=None):
        return await self.reasoning.think(context, system_prompt=system_prompt)

    async def submit_task(self, task: Task):
        """Submit a task to the swarm."""
        task.status = TaskStatus.PENDING
        self.pool[task.id] = task
        msg = GossipMessage(
            msg_type="TASK_BROADCAST",
            payload=task.to_dict(),
        )
        await self.gossip.inject(msg)
        if self.bus is not None:
            await self.bus.publish(TaskCreated(task.id))
        logger.info("Task submitted to swarm: %s (%s)", task.id, task.description)

    async def claim_task(self, task_id: str):
        """Try to claim a task from the swarm."""
        task = self.pool.get(task_id)
        if not task:
            logger.warning("Attempted to claim unknown task: %s", task_id)
            return False

        if task.status != TaskStatus.PENDING:
            logger.info("Task %s already %s", task_id, task.status.value)
            return False

        # Resolve creator address
        host, port = None, 0
        if task.creator_address:
            host, port_s = task.creator_address.split(":")
            port = int(port_s)
        elif hasattr(self, "peer_registry"):
            peer = self.peer_registry.get(task.creator_id)
            if peer and peer.address:
                host, port_s = peer.address.split(":")
                port = int(port_s)
        
        if not port:
             logger.error("Cannot claim task %s: creator address unknown for %s", task_id, task.creator_id)
             return False

        # Use RPC to confirm claim with creator
        try:
            result = await self.rpc_client.call(
                host, port, "task_claim",
                {"task_id": task_id, "worker_id": self.node_id}
            )
            if result.get("success"):
                task.status = TaskStatus.CLAIMED
                task.assigned_to = self.node_id
                await self.task_queue.put(task)
                logger.info("Successfully claimed task %s", task_id)
                return True
            else:
                logger.info("Failed to claim task %s: %s", task_id, result.get("reason"))
                return False
        except Exception as exc:
            logger.error("Error claiming task %s: %s", task_id, exc)
            return False

    async def handle_gossip(self, msg: GossipMessage):
        """Handle incoming task-related gossip."""
        if msg.msg_type == "TASK_BROADCAST":
            task_data = msg.payload
            task_id = task_data.get("id")
            if task_id not in self.pool:
                task = Task.from_dict(task_data)
                self.pool[task_id] = task
                logger.info("Learned about new swarm task: %s", task_id)

    async def run(self):
        self._running = True
        self.repair_loop.start()
        self._loop_task = asyncio.create_task(self._process_queue())
        logger.info("SwarmAgent started (node_id=%s)", self.node_id)

    async def stop(self):
        self._running = False
        await self.repair_loop.stop()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def _process_queue(self):
        while self._running:
            try:
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                await self._execute_task(task)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            except Exception as exc:
                logger.error("Task execution loop error: %s", exc)

    async def _execute_task(self, task: Task):
        logger.info("Executing task: %s", task.id)
        try:
            # We use the existing executor
            await self.executor.execute(task)
            
            # Report back to creator if not self
            if task.creator_id != self.node_id:
                await self.rpc_client.call(
                    task.creator_id, 0, "task_report",
                    {"task_id": task.id, "result": task.result, "status": task.status.value}
                )
        except Exception as exc:
            logger.error("Error in _execute_task for %s: %s", task.id, exc)
            task.status = TaskStatus.FAILED
            task.result = str(exc)
            if task.creator_id != self.node_id:
                await self.rpc_client.call(
                    task.creator_id, 0, "task_report",
                    {"task_id": task.id, "result": str(exc), "status": "failed"}
                )

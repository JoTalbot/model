import asyncio
import pytest
from swarm.agent.core import Task, SwarmAgent, TaskStatus
from swarm.network.gossip import GossipProtocol, GossipMessage
from swarm.network.rpc import RPCServer, RPCClient

class MockMemory:
    def __init__(self):
        self._node_id = "test-node"
    async def store(self, block):
        return "mock-block-id"

class MockLLM:
    async def complete(self, messages):
        return "mock result"

@pytest.mark.asyncio
async def test_distributed_task_lifecycle():
    # Node A (Creator)
    gossip_a = GossipProtocol(port=9001, interval=0.1)
    rpc_server_a = RPCServer(port=11001)
    rpc_client_a = RPCClient()
    agent_a = SwarmAgent("node-a", MockMemory(), MockLLM(), gossip_a, rpc_client_a)

    # Node B (Worker)
    gossip_b = GossipProtocol(port=9002, interval=0.1)
    rpc_server_b = RPCServer(port=11002)
    rpc_client_b = RPCClient()
    agent_b = SwarmAgent("node-b", MockMemory(), MockLLM(), gossip_b, rpc_client_b)

    # Register claim handler on Node A
    async def task_claim_handler(params):
        task = agent_a.pool.get(params["task_id"])
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CLAIMED
            task.assigned_to = params["worker_id"]
            return {"success": True}
        return {"success": False, "reason": "not_pending" if task else "not_found"}

    async def task_report_handler(params):
        task = agent_a.pool.get(params["task_id"])
        if task:
            task.status = TaskStatus(params["status"])
            task.result = params["result"]
            return {"success": True}
        return {"success": False}

    rpc_server_a.register("task_claim", task_claim_handler)
    rpc_server_a.register("task_report", task_report_handler)

    # Manual peer connection for gossip
    gossip_a.add_peer("127.0.0.1", 9002)
    gossip_b.add_peer("127.0.0.1", 9001)

    # Setup gossip handlers
    async def gossip_handler_a(msg):
        await agent_a.handle_gossip(msg)
    async def gossip_handler_b(msg):
        await agent_b.handle_gossip(msg)

    gossip_a._on_message = gossip_handler_a
    gossip_b._on_message = gossip_handler_b

    await gossip_a.start()
    await rpc_server_a.start()
    await gossip_b.start()
    await rpc_server_b.start()
    await agent_b.run()

    try:
        # 1. Node A submits a task
        task = Task(description="Do something important", creator_id="node-a")
        
        # Patch rpc_client to talk directly to Node A's port
        original_call = rpc_client_b.call
        async def mock_call(host, port, method, params):
            return await original_call("127.0.0.1", 11001, method, params)
        rpc_client_b.call = mock_call

        await agent_a.submit_task(task)

        # Register node-a in node-b peer_registry so claim_task resolves address
        from swarm.network.handshake import PeerKeyRegistry
        if not hasattr(agent_b, "peer_registry") or agent_b.peer_registry is None:
            agent_b.peer_registry = PeerKeyRegistry()
        agent_b.peer_registry.register("node-a", "pub_a", "127.0.0.1:11001")
        # Wait for gossip to propagate
        for _ in range(20):
            if task.id in agent_b.pool:
                break
            await asyncio.sleep(0.1)
        assert task.id in agent_b.pool

        # 2. Node B claims the task
        claimed = await agent_b.claim_task(task.id)
        assert claimed is True
        assert agent_a.pool[task.id].status == TaskStatus.CLAIMED

        # 3. Wait for execution and report
        for _ in range(30):
            if agent_a.pool[task.id].status == TaskStatus.DONE:
                break
            await asyncio.sleep(0.1)

        assert agent_a.pool[task.id].status == TaskStatus.DONE
        assert agent_a.pool[task.id].result == "mock result"

    finally:
        await agent_b.stop()
        await gossip_a.stop()
        await rpc_server_a.stop()
        await gossip_b.stop()
        await rpc_server_b.stop()
        await rpc_client_a.close()
        await rpc_client_b.close()

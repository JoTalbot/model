import pytest

from swarm.network.rpc import RPCClient, RPCServer


@pytest.mark.asyncio
async def test_rpc_call_and_response():
    async def echo_handler(params: dict) -> dict:
        return {"echo": params["msg"]}

    server = RPCServer(host="127.0.0.1", port=19000)
    server.register("echo", echo_handler)
    await server.start()

    try:
        client = RPCClient()
        response = await client.call("127.0.0.1", 19000, "echo", {"msg": "hello"})
        assert response == {"echo": "hello"}
    finally:
        await server.stop()
        await client.close()


@pytest.mark.asyncio
async def test_rpc_unknown_method():
    server = RPCServer(host="127.0.0.1", port=19001)
    await server.start()

    try:
        client = RPCClient()
        response = await client.call("127.0.0.1", 19001, "nonexistent", {})
        assert "error" in response
    finally:
        await server.stop()
        await client.close()


@pytest.mark.asyncio
async def test_rpc_multiple_methods():
    async def add_handler(params: dict) -> dict:
        return {"result": params["a"] + params["b"]}

    async def greet_handler(params: dict) -> dict:
        return {"greeting": f"Hello, {params['name']}!"}

    server = RPCServer(host="127.0.0.1", port=19002)
    server.register("add", add_handler)
    server.register("greet", greet_handler)
    await server.start()

    try:
        client = RPCClient()
        r1 = await client.call("127.0.0.1", 19002, "add", {"a": 2, "b": 3})
        assert r1 == {"result": 5}
        r2 = await client.call("127.0.0.1", 19002, "greet", {"name": "Василий"})
        assert r2 == {"greeting": "Hello, Василий!"}
    finally:
        await server.stop()
        await client.close()


@pytest.mark.asyncio
async def test_rpc_client_no_proxy():
    """RPCClient без прокси — прямое соединение."""
    async def handler(params):
        return {"ok": True}

    server = RPCServer(host="127.0.0.1", port=19003)
    server.register("test", handler)
    await server.start()

    try:
        client = RPCClient(proxy=None)
        r = await client.call("127.0.0.1", 19003, "test", {})
        assert r == {"ok": True}
    finally:
        await server.stop()
        await client.close()


@pytest.mark.asyncio
async def test_rpc_client_proxy_attribute():
    """RPCClient сохраняет proxy-настройку."""
    client = RPCClient(proxy="socks5://127.0.0.1:9050")
    assert client._proxy == "socks5://127.0.0.1:9050"
    await client.close()


@pytest.mark.asyncio
async def test_rpc_client_default_no_proxy():
    """По умолчанию proxy=None."""
    client = RPCClient()
    assert client._proxy is None
    await client.close()

import asyncio
import pytest
import os
from swarm.network.tor import TorManager

@pytest.mark.asyncio
async def test_tor_manager_simulation(tmp_path):
    # Setup mock data dir
    tor_dir = tmp_path / "tor"
    tor_dir.mkdir()
    (tor_dir / "hostname").write_text("test-onion-address.onion")
    
    tm = TorManager(
        proxy_url="socks5://127.0.0.1:9050",
        control_port=9051,
        tor_data_dir=str(tor_dir)
    )
    
    # We'll mock _check_proxy to return True
    async def mock_check_proxy():
        return True
    tm._check_proxy = mock_check_proxy
    
    onion = await tm.start()
    
    assert onion == "test-onion-address.onion"
    status = tm.get_status()
    assert status.is_running is True
    assert status.onion_address == onion
    
    await tm.stop()
    assert tm.get_status().is_running is False

@pytest.mark.asyncio
async def test_tor_manager_no_proxy():
    tm = TorManager(proxy_url="socks5://127.0.0.1:9999") # Bad proxy
    
    # Mock _check_proxy to return False
    async def mock_check_proxy():
        return False
    tm._check_proxy = mock_check_proxy
    
    onion = await tm.start()
    assert onion is None
    assert tm.get_status().is_running is False

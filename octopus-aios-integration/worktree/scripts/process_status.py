import asyncio
import sys
import json
from swarm.network.rpc import RPCClient

async def main():
    client = RPCClient()
    host = '127.0.0.1'
    port = 10000
    
    print('=== OCTOPUS SWARM PROCESS STATUS ===')
    
    # Node Status
    try:
        status = await client.call(host, port, 'node_status', {})
        print(f'Node ID: {status.get("node_id", "Unknown")}')
        print(f'Tor:     {status.get("tor", {}).get("status", "N/A")}')
    except:
        print('Node:    Offline or RPC error')

    # Recruitment Stats
    try:
        recruit = await client.call(host, port, 'recruit_stats', {})
        r = recruit.get('recruiter', {})
        h = recruit.get('handler', {})
        print(f'Recruitment: {r.get("recruited", 0)} recruited, {h.get("active_children", 0)} active children')
    except:
        print('Recruitment: Error fetching stats')

    # Memory Stats
    try:
        metrics = await client.call(host, port, 'memory_metrics', {}) # Check if this RPC exists
        # If not, use node_info or something
    except:
        pass

    # Peer List
    try:
        peers = await client.call(host, port, 'peer_list', {})
        print(f'Peers:   {len(peers.get("peers", []))} verified')
    except:
        print('Peers:   Error fetching peer list')
        
    print('====================================')

if __name__ == "__main__":
    asyncio.run(main())

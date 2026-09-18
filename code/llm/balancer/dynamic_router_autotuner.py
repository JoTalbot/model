"""AIOS Dynamic Router Auto-Tuner & Continuous Model Benchmarking Daemon.
Periodically measures RTT, latency, and success rates across all 13 Groq keys and cloud/local providers,
dynamically optimizing provider weights in the Smart Router.
"""
import os, sys, time, json, asyncio
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, '/opt')
sys.path.insert(0, '/opt/aios')

try:
    from aios.llm.llm_balancer import LLMBalancer
    balancer = LLMBalancer.get_instance()
except Exception:
    balancer = None

BENCHMARK_FILE = Path('/var/lib/octopus/provider_benchmarks.json')

async def benchmark_all_providers() -> Dict[str, Any]:
    if not balancer:
        return {"error": "LLMBalancer unavailable"}
        
    t_start = time.time()
    results = []
    
    for provider in balancer.providers:
        if not provider.is_available():
            results.append({"name": provider.name, "tier": provider.tier, "healthy": False, "latency_ms": 9999.0})
            continue
            
        t0 = time.time()
        try:
            res = await asyncio.wait_for(provider.generate("Ping test. Reply OK.", system="Reply strictly in 1 word."), timeout=6.0)
            dt = round((time.time() - t0)*1000, 1)
            results.append({"name": provider.name, "tier": provider.tier, "healthy": True, "latency_ms": dt, "reply": res[:30]})
        except Exception as e:
            results.append({"name": provider.name, "tier": provider.tier, "healthy": False, "error": str(e)[:60], "latency_ms": 9999.0})
            
    # Sort results by latency
    sorted_results = sorted(results, key=lambda x: x["latency_ms"])
    
    # Auto-tune weights: top 3 fastest get weight 1, 2, 3
    for idx, r in enumerate(sorted_results):
        for p in balancer.providers:
            if p.name == r["name"] and r["healthy"]:
                p.weight = max(1, idx + 1)
                
    output = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "total_providers": len(balancer.providers),
        "total_benchmark_time_ms": round((time.time() - t_start)*1000, 1),
        "providers_ranked": sorted_results
    }
    
    BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARK_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    return output

def run_autotuner_sync():
    import asyncio
    try:
        return asyncio.run(benchmark_all_providers())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(benchmark_all_providers())
        finally:
            loop.close()

if __name__ == "__main__":
    print("⚡ Running AIOS Dynamic Router Auto-Tuner...")
    res = run_autotuner_sync()
    print(json.dumps(res, indent=2, ensure_ascii=False))

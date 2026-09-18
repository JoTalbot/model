from swarm.memory.port import MemoryMetrics


def test_metrics_increment():
    m = MemoryMetrics()
    m.record_put("file")
    m.record_get("file", ok=True)
    m.record_get("swarm", ok=False)
    assert m.puts["file"] == 1
    assert m.gets_ok["file"] == 1
    assert m.gets_err["swarm"] == 1

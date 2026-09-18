import importlib.util
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve()
RUNTIME = HERE.with_name("strict_iter_archive_gate.py")
if not RUNTIME.exists():
    RUNTIME = HERE.parent.parent / "code" / "run.py"
SPEC = importlib.util.spec_from_file_location("archiver", RUNTIME)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_archive_and_marker(tmp_path):
    reports = tmp_path / "reports"
    run = reports / "parallel_demo"
    batch = run / "wave_01" / "B01"
    batch.mkdir(parents=True)
    (run / "SUMMARY.md").write_text("done\n")
    (batch / "ITER_001.md").write_text("one\n")
    (batch / "ITER_002.md").write_text("two\n")
    (batch / "ITER_bad.md").write_text("keep\n")
    rows = mod.candidates(reports)
    assert rows == [run]
    result = mod.archive_run(run, reports / "_archives", True)
    assert result["ok"] and result["verified"]
    assert (run / "ITER_FILES_ARCHIVED.md").exists()
    assert (batch / "ITER_001.md").exists()  # archiver never deletes
    with tarfile.open(result["archive"], "r:gz") as tf:
        assert sorted(tf.getnames()) == ["wave_01/B01/ITER_001.md", "wave_01/B01/ITER_002.md"]


def test_incomplete_run_is_blocked(tmp_path):
    run = tmp_path / "reports" / "parallel_incomplete"
    run.mkdir(parents=True)
    (run / "ITER_001.md").write_text("x\n")
    assert mod.candidates(run.parent) == []
    result = mod.archive_run(run, tmp_path / "archives", True)
    assert not result["verified"]
    assert "completion evidence missing" in result["errors"]
    assert (run / "ITER_001.md").exists()

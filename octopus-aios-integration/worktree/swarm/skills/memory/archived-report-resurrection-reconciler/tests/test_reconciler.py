import hashlib
import importlib.util
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve()
RUNTIME = HERE.with_name("archived_report_reconciler.py")
if not RUNTIME.exists():
    RUNTIME = HERE.parent.parent / "code" / "run.py"
SPEC = importlib.util.spec_from_file_location("reconciler", RUNTIME)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_verified_apply_removes_only_strict_iter(tmp_path):
    reports = tmp_path / "reports"
    run = reports / "run1"
    batch = run / "wave_01" / "B01"
    batch.mkdir(parents=True)
    strict = batch / "ITER_001.md"
    strict.write_text("evidence\n")
    keep = batch / "SUMMARY.md"
    keep.write_text("keep\n")
    near = batch / "ITER_bad.md"
    near.write_text("keep too\n")
    archive = tmp_path / "iter.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(strict, arcname="wave_01/B01/ITER_001.md")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    marker = run / "ITER_FILES_ARCHIVED.md"
    marker.write_text(f"archive={archive}\narchive_sha256={digest}\niter_files_archived=1\nrestore_smoke=success\n")
    row = mod.reconcile_run(marker, True)
    assert row["ok"] is True
    assert row["removed"] == 1
    assert not strict.exists()
    assert keep.exists() and near.exists() and marker.exists()


def test_hash_mismatch_blocks_delete(tmp_path):
    run = tmp_path / "reports" / "run1"
    run.mkdir(parents=True)
    strict = run / "ITER_001.md"
    strict.write_text("evidence\n")
    archive = tmp_path / "iter.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(strict, arcname="ITER_001.md")
    marker = run / "ITER_FILES_ARCHIVED.md"
    marker.write_text(f"archive={archive}\narchive_sha256={'0'*64}\niter_files_archived=1\n")
    row = mod.reconcile_run(marker, True)
    assert row["verified"] is False
    assert strict.exists()
    assert "archive sha256 mismatch" in row["errors"]

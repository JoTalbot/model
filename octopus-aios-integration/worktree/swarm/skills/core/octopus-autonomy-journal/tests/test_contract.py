from pathlib import Path
import importlib.util

SKILL_DIR = Path(__file__).resolve().parents[1]


def test_skill_contract_files_exist():
    assert (SKILL_DIR / "SKILL.md").exists()
    assert (SKILL_DIR / "code" / "run.py").exists() or (SKILL_DIR / "code.py").exists()


def test_skill_has_algorithm_and_control_section():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    assert "## Алгоритм" in text
    assert "## Контроль и развитие" in text


def test_generated_runtime_importable_if_present():
    run_py = SKILL_DIR / "code" / "run.py"
    if run_py.exists():
        spec = importlib.util.spec_from_file_location("skill_run_contract", run_py)
        assert spec is not None

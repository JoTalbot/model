from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def default_config():
    with open(PROJECT_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def mock_llm_response():
    return "This is a mock LLM response for testing."

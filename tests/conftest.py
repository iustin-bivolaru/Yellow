from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def cfg():
    from yellow.config import load_config

    return load_config(REPO / "config.yaml")

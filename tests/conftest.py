import os
from pathlib import Path

import pytest

_ENV_PREFIXES = ("GITLAB_", "MCP_", "LOG_")


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)

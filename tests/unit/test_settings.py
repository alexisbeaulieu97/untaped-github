from __future__ import annotations

import pytest
from pydantic import ValidationError

from untaped_github.settings import GithubSettings


def test_sweep_settings_defaults() -> None:
    settings = GithubSettings()

    assert settings.sweep.fetch_depth == 1
    assert settings.sweep.max_age_seconds == 3600
    assert settings.sweep.sync_concurrency == 12


@pytest.mark.parametrize(
    "sweep",
    [
        {"fetch_depth": -1},
        {"max_age_seconds": -1},
        {"sync_concurrency": 0},
    ],
)
def test_sweep_settings_reject_invalid_operational_values(sweep: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        GithubSettings(sweep=sweep)  # type: ignore[arg-type]

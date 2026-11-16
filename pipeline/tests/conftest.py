"""Shared test setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import collect_board


@pytest.fixture(autouse=True)
def _stubbed_config_declares_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A collect run whose ``load_schools`` a test stubs reads no declarations.

    Those tests hand ``collect_board.run`` a config path that does not exist
    and replace ``load_schools`` with their stanzas; the run's
    ``[[not_a_programme]]`` list comes from the same path, so a missing file
    stands for a config with none. A real file is read as usual.
    """
    real = collect_board.load_declared_strangers

    def load(path=None):  # type: ignore[no-untyped-def]
        if path is not None and not Path(path).is_file():
            return []
        return real() if path is None else real(path)

    monkeypatch.setattr(collect_board, "load_declared_strangers", load)

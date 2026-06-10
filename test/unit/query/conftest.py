"""Fixtures for the query unit suite. Fakes live in ``fakes.py`` (importable as a
bare module under pytest prepend mode); this exposes them as fixtures."""

from __future__ import annotations

import pytest

from fakes import FakeEmbedder, FakeRepository


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()

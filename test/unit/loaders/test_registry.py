"""Registry — all_connectors() covers exactly the SourceType vocabulary, and
discover_all() partitions a tree disjointly, raising on any double-claim.
"""

from __future__ import annotations

import pytest

from helixpay.contracts import SourceType
from helixpay.ingest.loaders import LoaderError, all_connectors, discover_all


def test_all_connectors_cover_every_source_type():
    connectors = all_connectors()
    types = {c.source_type for c in connectors}
    assert types == {e.value for e in SourceType}
    # exactly one connector per source_type (a duplicate would collapse in the set)
    assert len(connectors) == len(SourceType)


def _make_tree(root):
    (root / "overview.md").write_text("# o", encoding="utf-8")
    (root / "x.pdf").write_bytes(b"%PDF-1.4")
    (root / "interviews" / "sales").mkdir(parents=True)
    (root / "interviews" / "sales" / "a.md").write_text("# a", encoding="utf-8")
    (root / "chat").mkdir()
    (root / "chat" / "c.md").write_text("# c", encoding="utf-8")
    (root / "email").mkdir()
    (root / "email" / "e.md").write_text("from", encoding="utf-8")
    (root / "code").mkdir()
    (root / "code" / "co.md").write_text("# code", encoding="utf-8")
    (root / "dashboards").mkdir()
    (root / "dashboards" / "d.html").write_text("<html></html>", encoding="utf-8")
    (root / "images").mkdir()
    (root / "images" / "i.jpeg").write_bytes(b"\xff\xd8\xff\xe0")


def test_discover_all_partitions_disjointly(tmp_path):
    _make_tree(tmp_path)
    pairs = discover_all(str(tmp_path))
    paths = [p for _, p in pairs]
    assert len(paths) == len(set(paths)) == 8  # every file claimed exactly once
    by_type = {}
    for conn, p in pairs:
        by_type.setdefault(conn.source_type, []).append(p)
    assert len(by_type["md"]) == 2  # overview + interview
    assert set(by_type) >= {"md", "pdf", "html", "image", "slack", "email", "code"}


def test_discover_all_raises_on_double_claim(monkeypatch):
    from helixpay.ingest.loaders import base

    class _Greedy:
        source_type = "md"

        def discover(self, root):
            return ["same/path.md"]

        def load(self, path):  # pragma: no cover - not exercised
            raise NotImplementedError

    import helixpay.ingest.loaders as reg

    monkeypatch.setattr(reg, "all_connectors", lambda: [_Greedy(), _Greedy()])
    with pytest.raises(LoaderError) as ei:
        discover_all("anywhere")
    assert "same/path.md" in str(ei.value)

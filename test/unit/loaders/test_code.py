"""CodeConnector — contributor-analysis markdown; repo/owner tables stay atomic
so file/author references are not split apart.
"""

from __future__ import annotations

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.code import CodeConnector

_DOC = """# HelixPay Engineering — Contributor Analysis, Q1 2026

*Author: Vikram Patel. Generated 2026-04-08.*

## Repositories in scope

| Repository | Primary owner | Scope |
| helixpay/core | Sara Wijaya | Payments core |
| helixpay/pos-app | Ahmad Rashid | POS terminal app |

Across all repos, ~62% of Q1 commit volume is tagged to Confluence.
"""


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_code_preserves_repo_owner_table(tmp_path):
    path = _write(tmp_path, "contributors-analysis-q1-2026.md", _DOC)
    doc, chunks = CodeConnector().load(path)
    assert doc.source_type == SourceType.code.value
    # the repo→owner row is intact (file ref and author together) in one chunk
    assert any(
        "helixpay/core" in c.text and "Sara Wijaya" in c.text and "helixpay/pos-app" in c.text
        for c in chunks
    )


def test_code_as_of_from_generated_date(tmp_path):
    from datetime import date

    path = _write(tmp_path, "contributors-analysis-q1-2026.md", _DOC)
    doc, _ = CodeConnector().load(path)
    assert doc.as_of == date(2026, 4, 8)

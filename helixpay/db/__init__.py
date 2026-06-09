"""Infrastructure layer: the only place that touches Postgres directly.

All raw SQL is confined here (CLAUDE.md §7). Everything else uses the
``Repository`` Protocol via ``PostgresRepository``.
"""

from .repository import PostgresRepository

__all__ = ["PostgresRepository"]

"""HelixPay eval & ground-truth harness (Agent 6, author-independent).

The harness codes ONLY against ``helixpay.contracts`` (the frozen Protocols) and the
raw ``data/`` files — never against any build slice's implementation. The concrete
``QueryEngine`` is resolved lazily at run time (see ``eval.run.build_engine``), so the
oracle stays independent of the code it grades.
"""

from __future__ import annotations

__all__ = ["models", "run"]

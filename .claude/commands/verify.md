---
description: Verify the build — tests then the eval demo
---

Run the test suite and the eval demo. Green means: every golden fact is extracted
with the right `source_uri` + `as_of`, every deep question in `eval/questions.yaml`
answers with `as_of`-stamped citations, and at least one answer surfaces a real
planted contradiction.

> Depends on Agent 5's Makefile + Agent 6's harness. Once they land:
>
> ```bash
> make test && make demo
> ```
>
> Gate-level checks available now:
>
> ```bash
> uv run pytest test            # unit + (DB-gated) integration
> uv run mypy helixpay          # contract/signature conformance
> ```

Required env for the DB/eval paths: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.

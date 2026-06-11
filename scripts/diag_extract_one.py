"""One-shot extraction diagnostic (1 paid LLM call) — dump raw model output + parse error.

Renders the extract prompt for a single document's chunk(s) and calls the LLM once per chunk
with NO repair/glean, printing stop_reason, raw length, head/tail, and the JSON parse error.
Used to root-cause an empty/undecodable extraction (SP_026) without re-running the pipeline.
"""

from __future__ import annotations

import sys

from helixpay.ingest.extract.extractor import _SYSTEM  # type: ignore[attr-defined]
from helixpay.ingest.extract.llm import AnthropicClient, _generate, _try_parse  # type: ignore[attr-defined]
from helixpay.ingest.extract.prompts import render
from helixpay.ingest.extract.schemas import RawExtraction
from helixpay.ingest.loaders import discover_all


def main(argv: list[str] | None = None) -> int:
    target = (argv or sys.argv[1:])[0]
    client = AnthropicClient()
    for conn, path in discover_all("data"):
        if path != target:
            continue
        doc, chunks = conn.load(path)
        sys.stderr.write(f"{path}: {len(chunks)} chunk(s)\n")
        for ch in chunks:
            user = render(
                "extract_claims",
                source_type=doc.source_type,
                source_uri=doc.source_uri,
                as_of=(doc.as_of.isoformat() if doc.as_of else "unknown"),
                roster_hint="(none provided)",
                chunk_text=ch.text,
            )
            res = _generate(client, system=_SYSTEM, user=user, max_tokens=8192)
            raw = res.text
            parsed, err = _try_parse(raw, RawExtraction)
            sys.stderr.write(
                f"\n--- chunk {ch.ordinal} ---\n"
                f"stop_reason = {res.stop_reason!r}\n"
                f"raw_len     = {len(raw)}\n"
                f"parsed_ok   = {parsed is not None}\n"
                f"parse_error = {err!r}\n"
                f"HEAD:\n{raw[:600]}\n"
                f"TAIL:\n{raw[-600:]}\n"
            )
        return 0
    sys.stderr.write(f"no match for {target!r}\n")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

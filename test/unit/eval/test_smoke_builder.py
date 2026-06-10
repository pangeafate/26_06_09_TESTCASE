"""SP_015 — the one-per-type smoke corpus builder (deterministic, no DB/net).

Mirrors the verified `eval/sample/build_sample.py` contract: copy exactly one doc per
archetype into `eval/smoke/data/<subpath>` so `source_uri` matches the golden refs
verbatim, and filter the verified golden oracle down to those docs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.smoke.manifest import ARCHETYPES, MANIFEST, SOURCE_URIS

ROOT = Path(__file__).resolve().parents[3]


def test_manifest_is_one_per_type() -> None:
    # exactly one document per archetype; no archetype or source_uri repeated.
    assert len(MANIFEST) == len(set(ARCHETYPES)), "an archetype is repeated"
    assert len(MANIFEST) == len(set(SOURCE_URIS)), "a source_uri is repeated"
    assert len(MANIFEST) >= 8, "expected the full archetype spread (md/pdf/html/email/interview/org/code/chat/image)"


def test_manifest_docs_exist_on_disk() -> None:
    for _arch, uri, _why in MANIFEST:
        assert (ROOT / uri).is_file(), f"manifest doc missing from corpus: {uri}"


def test_every_manifest_doc_is_golden_bearing() -> None:
    # the golden+ledger bar can only score a doc that has >=1 golden fact.
    import yaml  # type: ignore[import-untyped]

    golden = yaml.safe_load((ROOT / "test" / "golden" / "facts.yaml").read_text())
    golden_uris = {f.get("source_uri") for f in golden.get("facts", [])}
    for _arch, uri, _why in MANIFEST:
        assert uri in golden_uris, f"{uri} has no golden fact — cannot score it on the cheap bar"


def test_build_copies_and_filters(tmp_path: Path) -> None:
    from eval.smoke.build_smoke import build

    summary = build(source_root=ROOT, dest_root=tmp_path)

    # 1) all docs copied, preserving the data/-relative subpath (source_uri parity).
    for _arch, uri, _why in MANIFEST:
        assert (tmp_path / "eval" / "smoke" / uri).is_file(), f"{uri} not copied"

    # 2) golden filtered to exactly the manifest source_uris, none silently golden-less.
    import yaml  # type: ignore[import-untyped]

    facts = yaml.safe_load((tmp_path / "eval" / "smoke" / "facts.yaml").read_text())
    kept_uris = {f["source_uri"] for f in facts["facts"]}
    assert kept_uris <= set(SOURCE_URIS)
    assert kept_uris == set(SOURCE_URIS), "some manifest doc dropped out of the filtered golden"
    assert summary["docs"] == len(MANIFEST)
    assert summary["facts"] >= len(MANIFEST)


def test_build_is_deterministic(tmp_path: Path) -> None:
    from eval.smoke.build_smoke import build

    from eval.smoke.check_smoke import corpus_fingerprint

    a = build(source_root=ROOT, dest_root=tmp_path / "a")
    b = build(source_root=ROOT, dest_root=tmp_path / "b")
    assert a == b
    fa = (tmp_path / "a" / "eval" / "smoke" / "facts.yaml").read_text()
    fb = (tmp_path / "b" / "eval" / "smoke" / "facts.yaml").read_text()
    assert fa == fb
    # copied doc bytes are identical too — the corpus fingerprint must be stable across builds.
    rel = [f"eval/smoke/{u}" for u in SOURCE_URIS]
    assert corpus_fingerprint(tmp_path / "a", rel) == corpus_fingerprint(tmp_path / "b", rel)


def test_build_raises_on_missing_doc(tmp_path: Path) -> None:
    # a source root with none of the docs present must fail loudly, not silently skip.
    from eval.smoke.build_smoke import build

    with pytest.raises(SystemExit):
        build(source_root=tmp_path, dest_root=tmp_path / "out")

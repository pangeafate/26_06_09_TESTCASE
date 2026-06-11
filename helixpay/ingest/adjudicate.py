"""LLM contradiction adjudication — the paid refiner on top of the SP_028a deterministic sweep
(SP_028b; CLAUDE.md §7 ontology — never resolve, both sides cited).

SP_028a's clear-then-rewrite sweep took the live contradiction set 266 → 115 at $0 by killing the
format / multi-valued / breakdown spurious classes. The residual 115 are mostly *distinct
phrasings of one semantic conflict* ("end of Q3" ≡ "Sep 30 2026") plus the genuine conflicts the
same-predicate lexical comparator structurally cannot see (cross-predicate, and the solid-vs-dotted
org-line case). This module judges each candidate **cluster** with an Opus call (temperature 0):

* **precision** — the LLM may return NO pair for a lexical candidate it judges to be the same fact
  in different words → no row (it overrules `detect`);
* **recall** — it may emit a genuine cross-predicate claim pair or a link↔link pair the comparator
  never compared;
* **never resolves** — the output schema has NO winner field; both claims/links coexist and are
  cited. A row is one homogeneous pair (two claims OR two links — never mixed).

Design (each tied to a Stage-3 finding):

* **Two labeled, signature-sorted blocks.** A cluster is a CLAIM block (``C1..Cn``) and a LINK
  block (``L1..Lm``). The LLM names a pair by ``block`` + two 1-based indices INTO that block, so a
  claim↔link pair — which ``Contradiction`` cannot represent — is structurally impossible. Each
  block is sorted by its semantic signature BEFORE numbering (on write AND on cache read), so a
  re-seed that renumbers surrogate ids yields the identical index→member mapping.
* **Content-hash cache.** Keyed on ``(model, prompt_version, norm_version, sorted member
  signatures)`` — NOT surrogate row ids, and ``source_uri`` is EXCLUDED (it can change on a
  re-record of the same fact). So a re-sweep of an unchanged store is $0.
* **Single-writer, fallback floor.** The sweep clears the table and is the only writer. A cluster
  whose verdict is ABSENT (LLM dropped / never ran) falls back to the SP_028a deterministic floor
  (value-pair dedup'd) so a real conflict is never lost. A verdict that is PRESENT but empty is the
  precision win — authoritative, no fallback.

All unit/integration tests run at $0 with an injected stub ``LLMClient`` + an in-memory cache.
The paid run is the gated ``scripts/adjudicate_contradictions.py`` CLI.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Hashable, Literal, Optional, Protocol, cast

from pydantic import BaseModel

from helixpay.config import SYNTHESIS_MODEL
from helixpay.contracts import Contradiction, Repository
from helixpay.ingest.contradict import detect, detect_link_conflicts
from helixpay.ingest.dedup import DedupWriter
from helixpay.ingest.extract.llm import AnthropicClient, LLMClient, call_structured
from helixpay.ingest.extract.prompts import load_prompt
from helixpay.ingest.normalize import normalize_value
from helixpay.ingest.predicate_cardinality import should_skip_predicate

log = logging.getLogger("helixpay.ingest.adjudicate")


class SweepRepository(Repository, Protocol):
    """The ``Repository`` Protocol plus the three pure-read/clear methods the post-ingest sweep
    needs (all already implemented by ``PostgresRepository``; SP_028a). Declared here as a
    structural extension so this ingest-layer module never imports the db (infrastructure) layer —
    layer boundary §4 (shared logic does not depend on infrastructure adapters)."""

    def distinct_claim_groups(self) -> list[tuple[int, str]]: ...
    def distinct_link_groups(self) -> list[tuple[int, str]]: ...
    def clear_contradictions(self) -> int: ...

# Cache-invalidation contract. Bump NORM_VERSION whenever normalize.py value-equality semantics
# change; bump PROMPT_VERSION on any prompts/adjudicate_contradictions.md edit. Both are folded
# into the cache key, so a bump forces a fresh adjudication (covered by the version-bump test).
NORM_VERSION = "sp028a-signfix"
PROMPT_VERSION = "1"
ADJUDICATE_MODEL = SYNTHESIS_MODEL  # claude-opus-4-8 (synthesis/ask tier, pinned)
PROMPT_NAME = "adjudicate_contradictions"

# Cross-predicate claim block is "all of one subject's live non-set_valued claims"; the link block
# is the subject's functional org edges. detect_link_conflicts only sweeps reports_to, so the LINK
# block is the ONLY place the solid-vs-dotted recall item can surface — dotted_line_to is included.
_CLUSTER_LINK_TYPES: tuple[str, ...] = ("reports_to", "dotted_line_to")

# Generous bound; oversized clusters fall back to the deterministic floor + a logged cap line so
# the operator sees any cross-predicate recall gap (HelixPay is the largest subject).
MAX_CLUSTER_MEMBERS = 40

_KINDS = ("value_conflict", "temporal", "source_disagreement")


# ─────────────────────────────────────────────────────────────────────────────
# Output schema (a NEW local schema — not forked from extract/schemas.py)
# ─────────────────────────────────────────────────────────────────────────────
class VerdictPair(BaseModel):
    """One genuine contradiction the LLM found, named by block + two 1-based indices into it.

    ``block`` selects the index space (claims or links); ``a``/``b`` are 1-based positions in that
    block. A pair NEVER crosses blocks, so it always maps to a homogeneous (claim,claim) or
    (link,link) ``Contradiction`` row. No winner field — both sides coexist."""

    block: Literal["claim", "link"]
    a: int
    b: int
    kind: Literal["value_conflict", "temporal", "source_disagreement"]
    rationale: str


class AdjudicationVerdict(BaseModel):
    """The LLM's verdict for one cluster: the genuine contradiction pairs (possibly none)."""

    contradictions: list[VerdictPair]


# ─────────────────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────────────────
class AdjudicationCache(Protocol):
    """A content-keyed verdict cache. Values are the JSON-able ``AdjudicationVerdict.model_dump``."""

    def get(self, key: str) -> Optional[dict]: ...
    def put(self, key: str, value: dict) -> None: ...


class DictCache:
    """In-memory cache for tests."""

    def __init__(self) -> None:
        self._d: dict[str, dict] = {}

    def get(self, key: str) -> Optional[dict]:
        return self._d.get(key)

    def put(self, key: str, value: dict) -> None:
        self._d[key] = value


class JsonFileCache:
    """One JSON file per cluster key under ``directory`` — survives process restarts ($0 replay)."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        p = self._path(key)
        if not p.is_file():
            return None
        return cast(dict, json.loads(p.read_text(encoding="utf-8")))

    def put(self, key: str, value: dict) -> None:
        self._path(key).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Cluster model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Member:
    kind: str  # "claim" | "link"
    row_id: int  # claim.id or link.id
    predicate: str  # canonical predicate (claim) or link_type (link)
    value: str  # object_value (claim) or "→<to_entity_id>" (link) — embedded verbatim in the note
    as_of: Optional[date]
    signature: tuple[str, ...]
    display: str  # the human line shown to the LLM


@dataclass(frozen=True)
class Cluster:
    subject_id: int
    claims: tuple[Member, ...]  # signature-sorted (tuple → frozen is actually immutable)
    links: tuple[Member, ...]  # signature-sorted

    def is_adjudicable(self) -> bool:
        """A homogeneous pair needs ≥2 members in at least one block."""
        return len(self.claims) >= 2 or len(self.links) >= 2

    def size(self) -> int:
        return len(self.claims) + len(self.links)


def _canon(repo: Repository, predicate: str) -> str:
    try:
        return repo.canonical_predicate(predicate)
    except Exception:  # noqa: BLE001 — canonical_predicate must never raise; be defensive anyway
        return predicate


def _claim_signature(subject_id: int, canonical_pred: str, value: Optional[str], as_of: Optional[date]) -> tuple[str, ...]:
    return ("claim", str(subject_id), canonical_pred, normalize_value(value or "")[0], as_of.isoformat() if as_of else "")


def _link_signature(subject_id: int, link_type: str, to_entity_id: int, as_of: Optional[date]) -> tuple[str, ...]:
    return ("link", str(subject_id), link_type, str(to_entity_id), as_of.isoformat() if as_of else "")


def build_cluster(repo: Repository, subject_id: int) -> Cluster:
    """Assemble the two signature-sorted blocks for one subject. set_valued claims are excluded
    (multiplicity is legitimate — SP_028a); the link block is the subject's functional org edges."""
    claim_members: list[Member] = []
    for c in repo.get_claims(subject_id, None):
        if c.id is None or c.superseded_by is not None:
            continue
        cp = _canon(repo, c.predicate)
        if should_skip_predicate(cp):
            continue
        claim_members.append(
            Member(
                kind="claim",
                row_id=c.id,
                predicate=cp,
                value=c.object_value or "",
                as_of=c.as_of,
                signature=_claim_signature(subject_id, cp, c.object_value, c.as_of),
                display=f'[{cp}] "{c.object_value}" as_of={c.as_of or "?"}',
            )
        )

    link_members: list[Member] = []
    for ltype in _CLUSTER_LINK_TYPES:
        for ln in repo.get_links(ltype, subject_id):
            if ln.id is None:
                continue
            link_members.append(
                Member(
                    kind="link",
                    row_id=ln.id,
                    predicate=ltype,
                    value=f"→{ln.to_entity_id}",
                    as_of=ln.as_of,
                    signature=_link_signature(subject_id, ltype, ln.to_entity_id, ln.as_of),
                    display=f"{ltype} → entity#{ln.to_entity_id} as_of={ln.as_of or '?'}",
                )
            )

    claim_members.sort(key=lambda m: m.signature)
    link_members.sort(key=lambda m: m.signature)
    return Cluster(subject_id=subject_id, claims=tuple(claim_members), links=tuple(link_members))


def cluster_cache_key(cluster: Cluster, *, model: str = ADJUDICATE_MODEL) -> str:
    """Content hash over (model, prompt_version, norm_version, sorted member signatures). Stable
    across surrogate-id renumbering and source_uri churn; invalidated by a version bump. JSON-
    serialized (not delimiter-joined) so a signature field can never collide across members. The
    ``model`` rides in the key so a Sonnet run and an Opus run never reuse each other's verdict."""
    sigs = sorted(list(m.signature) for m in (*cluster.claims, *cluster.links))
    blob = json.dumps([model, PROMPT_VERSION, NORM_VERSION, sigs], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic floor (value-pair dedup'd via the shared DedupWriter — never raw detect)
# ─────────────────────────────────────────────────────────────────────────────
def _deterministic_floor(
    repo: SweepRepository,
    subject_id: int,
    claim_groups: list[tuple[int, str]],
    link_groups: list[tuple[int, str]],
) -> int:
    """The SP_028a deterministic verdict for one subject (value-pair dedup'd). The fallback path.
    The caller passes the store-wide group lists once (fetched in ``adjudicate_store``) so the
    sweep stays one scan, not O(subjects × groups)."""
    written = 0
    for sid, predicate in claim_groups:
        if sid != subject_id or should_skip_predicate(_canon(repo, predicate)):
            continue
        claims = repo.get_claims(sid, predicate)
        keymap: dict[int, Hashable] = {
            c.id: normalize_value(c.object_value)[0] for c in claims if c.id is not None
        }
        w = DedupWriter(repo, keymap)
        detect(cast(Repository, w), sid, predicate)
        written += w.written
    for sid, link_type in link_groups:
        if sid != subject_id:
            continue
        links = repo.get_links(link_type, sid)
        tomap: dict[int, Hashable] = {ln.id: ln.to_entity_id for ln in links if ln.id is not None}
        w = DedupWriter(repo, tomap)
        detect_link_conflicts(cast(Repository, w), sid, link_type)
        written += w.written
    return written


# ─────────────────────────────────────────────────────────────────────────────
# LLM adjudication of one cluster
# ─────────────────────────────────────────────────────────────────────────────
def _render_user(cluster: Cluster) -> str:
    lines = ["CLAIMS:"]
    lines += [f"C{i}. {m.display}" for i, m in enumerate(cluster.claims, 1)] or ["(none)"]
    lines.append("")
    lines.append("LINKS:")
    lines += [f"L{i}. {m.display}" for i, m in enumerate(cluster.links, 1)] or ["(none)"]
    return "\n".join(lines)


def adjudicate_cluster(
    cluster: Cluster,
    client: LLMClient,
    cache: AdjudicationCache,
    *,
    model: str = ADJUDICATE_MODEL,
) -> Optional[AdjudicationVerdict]:
    """Return the cluster's verdict, from cache or one LLM call. ``None`` means the model output
    was undecodable (call_structured dropped it) → the caller falls back to the deterministic
    floor. An empty-but-present verdict is a real precision result and IS returned/cached.
    ``model`` must match the client's model so the cache key and the call agree."""
    key = cluster_cache_key(cluster, model=model)
    cached = cache.get(key)
    if cached is not None:
        return AdjudicationVerdict.model_validate(cached)
    result = call_structured(
        client,
        prompt_name=PROMPT_NAME,
        system=load_prompt(PROMPT_NAME),
        user=_render_user(cluster),
        schema=AdjudicationVerdict,
    )
    if result.value is None:
        return None  # undecodable — do not cache a failure; the caller falls back to the floor
    cache.put(key, result.value.model_dump())
    return result.value


def _write_verdict(repo: Repository, cluster: Cluster, verdict: AdjudicationVerdict) -> int:
    """Map each homogeneous pair to a Contradiction row (validate-and-drop on a bad index)."""
    written = 0
    for p in verdict.contradictions:
        block = cluster.claims if p.block == "claim" else cluster.links
        if not (1 <= p.a <= len(block)) or not (1 <= p.b <= len(block)) or p.a == p.b:
            log.warning(
                "adjudicate dropped pair (index out of range)",
                extra={"subject_id": cluster.subject_id, "block": p.block, "a": p.a, "b": p.b},
            )
            continue
        ma, mb = block[p.a - 1], block[p.b - 1]
        if p.block == "claim":
            note = f"[llm] {p.kind}: '{ma.value}' ({ma.as_of}) vs '{mb.value}' ({mb.as_of}) — {p.rationale}"
            row = Contradiction(
                subject_entity_id=cluster.subject_id, predicate=ma.predicate,
                claim_a_id=ma.row_id, claim_b_id=mb.row_id, kind=p.kind, note=note,
            )
        else:
            note = (
                f"[llm] {p.kind}: {ma.predicate} {ma.value} ({ma.as_of}) vs "
                f"{mb.predicate} {mb.value} ({mb.as_of}) — {p.rationale}"
            )
            row = Contradiction(
                subject_entity_id=cluster.subject_id, predicate=ma.predicate,
                link_a_id=ma.row_id, link_b_id=mb.row_id, kind=p.kind, note=note,
            )
        repo.add_contradiction(row)
        written += 1
    return written


# ─────────────────────────────────────────────────────────────────────────────
# The sweep
# ─────────────────────────────────────────────────────────────────────────────
def adjudicate_store(
    repo: SweepRepository,
    client: LLMClient,
    cache: AdjudicationCache,
    *,
    dry_run: bool = False,
    max_cluster_members: int = MAX_CLUSTER_MEMBERS,
    model: str = ADJUDICATE_MODEL,
) -> dict[str, int]:
    """Single-writer clear-then-rewrite sweep with an LLM refiner stage.

    ``dry_run`` is PRINT-ONLY: it builds clusters and counts cache misses but does NOT clear or
    write the table (spends nothing). A real run clears the table and, per subject: adjudicate the
    cluster (cache or one Opus call); write the verdict pairs; or, when the verdict is absent /
    the cluster is non-adjudicable / over the size cap, write the deterministic floor instead."""
    # Fetch the store-wide group lists ONCE and reuse them for subject enumeration and every floor
    # call, so the sweep is one scan rather than O(subjects × groups) (Stage-5 H2).
    claim_groups = repo.distinct_claim_groups()
    link_groups = repo.distinct_link_groups()
    subjects = sorted({sid for sid, _ in claim_groups} | {sid for sid, _ in link_groups})

    if dry_run:
        clusters = est = 0
        for sid in subjects:
            cl = build_cluster(repo, sid)
            if not cl.is_adjudicable() or cl.size() > max_cluster_members:
                continue
            clusters += 1
            if cache.get(cluster_cache_key(cl, model=model)) is None:
                est += 1
        return {
            "subjects": len(subjects), "clusters": clusters,
            "estimated_llm_calls": est, "cache_hits": clusters - est,
        }

    repo.clear_contradictions()
    stats = {
        "subjects": len(subjects), "clusters": 0, "llm_rows": 0,
        "floor_rows": 0, "capped": 0, "after": 0,
    }
    for sid in subjects:
        cl = build_cluster(repo, sid)
        if not cl.is_adjudicable():
            stats["floor_rows"] += _deterministic_floor(repo, sid, claim_groups, link_groups)
            continue
        if cl.size() > max_cluster_members:
            log.info(
                "adjudicate cluster over size cap → deterministic floor",
                extra={"subject_id": sid, "size": cl.size(), "cap": max_cluster_members},
            )
            stats["capped"] += 1
            stats["floor_rows"] += _deterministic_floor(repo, sid, claim_groups, link_groups)
            continue
        stats["clusters"] += 1
        verdict = adjudicate_cluster(cl, client, cache, model=model)
        if verdict is None:
            stats["floor_rows"] += _deterministic_floor(repo, sid, claim_groups, link_groups)
        else:
            stats["llm_rows"] += _write_verdict(repo, cl, verdict)

    stats["after"] = len(repo.get_contradictions())
    return stats


def build_adjudicator_client(model: str = ADJUDICATE_MODEL) -> AnthropicClient:
    """The paid client at temperature 0 (deterministic). Defaults to the Opus synthesis tier;
    the gated CLI may override ``model`` (e.g. the cheaper ``claude-sonnet-4-6``) — the chosen
    model rides in the cache key, so verdicts never cross model boundaries."""
    return AnthropicClient(model=model, temperature=0)


__all__ = [
    "VerdictPair",
    "AdjudicationVerdict",
    "AdjudicationCache",
    "DictCache",
    "JsonFileCache",
    "Member",
    "Cluster",
    "build_cluster",
    "cluster_cache_key",
    "adjudicate_cluster",
    "adjudicate_store",
    "build_adjudicator_client",
    "NORM_VERSION",
    "PROMPT_VERSION",
    "ADJUDICATE_MODEL",
    "MAX_CLUSTER_MEMBERS",
]

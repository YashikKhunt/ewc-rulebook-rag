"""Score retrieval + faithfulness against eval/queries.yaml.

CLAUDE.md: this must pass before any retrieval change is considered done. The exit
code is the regression gate:

    0   every must_pass assertion held (in every generation run) and every offline
        regression pin matched
    1   at least one must_pass assertion or regression pin failed
    2   configuration / budget refusal (nothing was scored)

Design decisions, with their evidence
-------------------------------------
* **must_pass vs known_fail.** The human ordered S4 built BEFORE the S5 fixes for
  B4/B5/B6/B7 precisely so those defects are quantified by a harness first. A
  known_fail assertion measures a deferred defect: it is reported ("CONFIRMED" when
  it fails at least once, "NOW PASSING" when it unexpectedly holds everywhere) and
  never blocks the exit code. Everything S3's verifier confirmed working is
  must_pass and gates.

* **Cost.** Retrieval checks are ~free (query embeddings; a router call only where
  `route: auto`). Generation is the cost, so it runs only on cases marked
  `generate: true`, only without --retrieval-only, and only after a tiktoken-exact
  prompt-size estimate is printed and checked against --max-usd (default $0.50,
  same guard shape as index.py). Actual measured spend is reported at the end from
  the models' own usage metadata.

* **Non-determinism (A2).** Generation is unseeded; temperature 0 is not
  deterministic. Handling, chosen and documented per the S4 brief: every generative
  case runs N times (config.runs, default 2; --runs overrides). Assertions are
  INVARIANTS (regex / citation / metadata checks), never exact-string comparisons.
  A must_pass assertion passes only if it holds in EVERY run — for a compliance
  tool a flaky pass is a fail. A known_fail is CONFIRMED if it fails in ANY run.

* **Mechanical over LLM-judge.** Every check here is a string/metadata assertion
  against the answer and the retrieved docs. No LLM judge is used anywhere:
  gpt-4o-mini judging gpt-4o-mini is weak evidence, and every behaviour under test
  (citations, leakage, abstention shape, hedges, verbatim runs) is mechanically
  checkable. The three auto-checks reuse or mirror graph.py's own machinery:

    - citations_supported: graph.unsupported_citations() over the run's own docs.
    - hedges_attributable: flags typically/usually/generally/commonly ONLY when the
      word appears in no retrieved excerpt (006 ruling 3: the corpus contains
      44/12/8/2 such chunks; a flat regex fails faithful answers — see the
      normal-dota2-attributable-hedge case, which exists to prove the detector
      does not fire on an attributable hedge).
    - verbatim_max_run: longest common word-run between the answer and any source
      chunk, threshold 25 words (justified in queries.yaml), known_fail -> B7.

Usage
-----
    python eval/run.py --retrieval-only        # offline pins + retrieval; ~free
    python eval/run.py                          # + generation subset, budget-guarded
    python eval/run.py --runs 3 --max-usd 0.10
    python eval/run.py --only conflict-media-fines --bucket conflict
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import graph  # noqa: E402

QUERIES = ROOT / "eval" / "queries.yaml"

HEDGES = ("typically", "usually", "generally", "commonly")
EST_OUTPUT_TOKENS = 500      # generous; 007 measured ~400 out per run
RETRY_FACTOR = 1.8           # 007: 17/25 runs took the bounded one-retry path
ROUTER_EST = (700, 15)       # tokens in/out per route call, measured order of magnitude

_WORD = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

class Result:
    """One assertion's aggregated outcome across runs."""

    def __init__(self, case: str, bucket: str, name: str, status: str,
                 passed_runs: list[bool], detail: str = "", finding: str = ""):
        self.case = case
        self.bucket = bucket
        self.name = name
        self.status = status            # "must_pass" | "known_fail"
        self.passed_runs = passed_runs  # one bool per run (offline/retrieval: one)
        self.detail = detail
        self.finding = finding

    @property
    def ok(self) -> bool:
        """A must_pass holds only if it held in EVERY run (A2: unseeded)."""
        return all(self.passed_runs)

    @property
    def confirmed(self) -> bool:
        """A known_fail is confirmed when it failed in at least one run."""
        return not all(self.passed_runs)

    def verdict(self) -> str:
        if self.status == "must_pass":
            return "PASS" if self.ok else "FAIL"
        return "KNOWN_FAIL (confirmed)" if self.confirmed else "KNOWN_FAIL NOW PASSING"


# ---------------------------------------------------------------------------
# Offline regression pins -- free, no network
# ---------------------------------------------------------------------------

def offline_checks(reg: dict) -> list[Result]:
    out: list[Result] = []

    def pin(name: str, got: Any, want: Any) -> None:
        out.append(Result("regression-pins", "regression", name, "must_pass",
                          [got == want], detail=f"want {want!r}, got {got!r}"))

    pkl = ROOT / graph._env("EWC_DATA_DIR", "data") / "chunks.pkl"
    blob = pkl.read_bytes()
    want = reg.get("chunks_pickle", {})
    pin("chunks.pkl sha256", hashlib.sha256(blob).hexdigest(), want.get("sha256"))
    pin("chunks.pkl bytes", len(blob), want.get("bytes"))

    chunks = graph.load_chunks()
    pin("pickled documents", len(chunks), want.get("documents"))

    import chromadb
    client = chromadb.PersistentClient(
        path=str(ROOT / graph._env("EWC_CHROMA_DIR", "data/chroma")))
    count = client.get_collection(
        graph._env("EWC_CHROMA_COLLECTION", "ewc_rulebooks")).count()
    pin("chroma vectors", count, reg.get("chroma_vectors"))

    per_book: dict[str, dict[str, Any]] = defaultdict(lambda: {"chunks": 0, "articles": set()})
    for doc in chunks:
        meta = doc.metadata
        row = per_book[meta["game"]]
        row["chunks"] += 1
        article = (meta.get("article") or "").strip()
        if article:
            row["articles"].add(article)
    want_books = reg.get("per_book", {})
    got_books = {g: {"chunks": r["chunks"], "articles": len(r["articles"])}
                 for g, r in per_book.items()}
    pin("book list", sorted(got_books), sorted(want_books))
    for game in sorted(want_books):
        pin(f"per-book {game}", got_books.get(game), want_books[game])

    # The amendment layer (S5). Contract #2 is unfalsifiable if the amendment
    # silently stops being indexed, so its presence is pinned offline and free.
    if "amendment_chunks" in reg:
        amendments = [d for d in chunks if d.metadata.get("scope") == "amendment"]
        pin("amendment chunks", len(amendments), reg["amendment_chunks"])
        pin("amendment targets",
            sorted({f"{d.metadata.get('amends_game')}:{d.metadata.get('amends_article')}"
                    for d in amendments}),
            sorted(reg.get("amendment_targets", [])))
    return out


# ---------------------------------------------------------------------------
# Retrieval phase -- query embeddings only (router call only where route: auto)
# ---------------------------------------------------------------------------

def resolve_case(case: dict, usage: list[dict]) -> tuple[Any, Any, list, str, str]:
    """(game_used, routed_slug_or_None, docs, scope, precedence_note).

    `routed` is meaningful only when the case asked for the router (route: auto).
    The note is what `resolve` computes for this pool -- free, no model call --
    and it is carried here so the cost estimate prices the prompt the pipeline
    will actually send."""
    game = case.get("game")
    routed: Any = "(forced)"
    if game is None and case.get("route") == "auto":
        state = graph.route({"question": case["question"]})
        routed = state["game"]
        game = routed
        usage.extend(state.get("usage") or [])
    part = graph.retrieve({"question": case["question"],
                           "query": case["question"], "game": game})
    resolved = graph.resolve({"docs": part["docs"], "ranks": part["ranks"]})
    return game, routed, part["docs"], part["scope"], resolved["note"]


def retrieval_checks(case: dict, routed: Any, docs: list) -> list[Result]:
    spec = case.get("retrieval") or {}
    cid, bucket = case["id"], case["bucket"]
    pool = [(d.metadata["game"], (d.metadata.get("article") or "").strip(),
             d.metadata.get("scope", "")) for d in docs]
    pool_str = ", ".join(f"{g}:{a or '-'}[{s}]" for g, a, s in pool)
    out: list[Result] = []

    for want in spec.get("must_include", []):
        # `scope:` is optional and only ever NARROWS the match. An amendment
        # shares its game and article number with the article it amends, so
        # asserting the amendment is in the pool is impossible without it.
        scope = want.get("scope")
        in_scope = [(g, a) for g, a, s in pool if scope is None or s == scope]
        suffix = f" [{scope}]" if scope else ""
        if "article_prefix" in want:
            prefix = want["article_prefix"]
            hit = any(g == want["game"] and (a == prefix or a.startswith(prefix + "."))
                      for g, a in in_scope)
            name = f"retrieve {want['game']}:{prefix}.*{suffix} in top {len(docs)}"
        else:
            hit = (want["game"], want["article"]) in in_scope
            name = f"retrieve {want['game']}:{want['article']}{suffix} in top {len(docs)}"
        out.append(Result(cid, bucket, name, want.get("status", "must_pass"),
                          [hit], detail=f"pool: {pool_str}",
                          finding=want.get("finding", "")))

    for slug in spec.get("must_exclude_games", []):
        leaked = [f"{g}:{a}" for g, a, _s in pool if g == slug]
        out.append(Result(cid, bucket, f"no {slug} chunks (leakage)", "must_pass",
                          [not leaked],
                          detail=f"leaked: {leaked}" if leaked else f"pool: {pool_str}"))

    if "route_expect" in spec:
        want = spec["route_expect"]
        want_val = None if want in (None, "none") else want
        out.append(Result(cid, bucket, f"router returns {want}", "must_pass",
                          [routed == want_val], detail=f"routed: {routed!r}"))

    if "only_scopes" in spec:
        allowed = set(spec["only_scopes"])
        stray = sorted({d.metadata["scope"] for d in docs} - allowed)
        out.append(Result(cid, bucket, f"scopes within {sorted(allowed)}", "must_pass",
                          [not stray], detail=f"stray scopes: {stray}" if stray else ""))
    return out


# ---------------------------------------------------------------------------
# Answer checks -- mechanical, per generated text
# ---------------------------------------------------------------------------

def parse_citations(text: str) -> list[tuple[str, str | None, int]]:
    """(book, article_or_None, page) for every citation-shaped locator in the
    answer, using graph.py's own extraction so eval and pipeline agree on what
    counts as a citation."""
    out: list[tuple[str, str | None, int]] = []
    for locator in graph.cited_locators(text):
        page_match = re.search(r"p\.(\d+)$", locator)
        if not page_match:
            continue
        page = int(page_match.group(1))
        match = graph._LOCATOR.match(locator)
        if match:
            out.append((match["book"].strip(),
                        match["article"].strip().rstrip("."), page))
        else:
            bare = re.match(r"^(.+?) — p\.\d+$", locator)
            if bare:
                out.append((bare.group(1).strip(), None, page))
    return out


def unattributable_hedges(text: str, docs: list) -> list[str]:
    """Hedge words in the answer with NO hedge in any retrieved excerpt.

    006 ruling 3: key on the excerpt text, not on quotation marks -- a paraphrased
    hedge in the model's own voice is attributable when the excerpt carries the
    hedging. Attribution is at the HEDGE-CLASS level, not the exact word: measured
    live (2026-08-13), a faithful dota2 repeat-offences answer paraphrased the
    excerpt's "usually" as "generally" before quoting "usually" verbatim --
    exact-word attribution flags that faithful paraphrase, which is precisely the
    false-positive class the ruling forbids. So the check fires only when the
    answer hedges while NO retrieved excerpt contains ANY of the four hedge words:
    then the hedge cannot have come from the evidence. Residual blind spot,
    accepted and documented: an answer could import its own hedge on point A while
    the pool happens to carry a hedged chunk about point B; sentence-level
    attribution is an S5+ refinement."""
    source = " ".join(d.page_content.lower() for d in docs)
    source_hedged = any(hedge in source for hedge in HEDGES)
    flagged = []
    for hedge in HEDGES:
        if re.search(rf"\b{hedge}\b", text, re.I) and not source_hedged:
            flagged.append(hedge)
    return flagged


def longest_verbatim_run(text: str, docs: list) -> tuple[int, str]:
    """Longest common contiguous word run between the answer and any one source
    chunk (punctuation/case-insensitive -- transcription does not stop being
    transcription when a comma changes)."""
    answer_words = _WORD.findall(text.lower())
    best, where = 0, ""
    for doc in docs:
        chunk_words = _WORD.findall(doc.page_content.lower())
        prev = [0] * (len(chunk_words) + 1)
        for word in answer_words:
            cur = [0] * (len(chunk_words) + 1)
            for j, chunk_word in enumerate(chunk_words, start=1):
                if word == chunk_word:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best:
                        best = cur[j]
                        meta = doc.metadata
                        where = (f"{meta['game']}:{meta.get('article') or '-'} "
                                 f"p.{meta['page']}")
            prev = cur
    return best, where


def answer_checks(case: dict, answers: list[str], docs_per_run: list[list],
                  config: dict) -> list[Result]:
    cid, bucket = case["id"], case["bucket"]
    out: list[Result] = []

    def excerpt(text: str) -> str:
        return " ".join(text.split())[:160]

    # --- declared assertions -------------------------------------------------
    for spec in case.get("answer", []):
        check = spec["check"]
        status = spec.get("status", "must_pass")
        finding = spec.get("finding", "")
        per_run: list[bool] = []
        details: list[str] = []

        for text in answers:
            if check == "require":
                hit = re.search(spec["pattern"], text, re.I) is not None
                per_run.append(hit)
                if not hit:
                    details.append(f"missing /{spec['pattern']}/")
            elif check == "require_any":
                hit = any(re.search(p, text, re.I) for p in spec["patterns"])
                per_run.append(hit)
                if not hit:
                    details.append(f"none of {spec['patterns']}")
            elif check == "forbid":
                match = re.search(spec["pattern"], text, re.I)
                per_run.append(match is None)
                if match:
                    details.append(f"matched {match.group(0)!r}")
            elif check == "require_citation":
                cites = parse_citations(text)
                pages = spec.get("pages")
                hit = any(book == spec["book"] and article == spec["article"]
                          and (pages is None or page in pages)
                          for book, article, page in cites)
                per_run.append(hit)
                if not hit:
                    details.append(f"cited: {cites}")
            elif check == "forbid_citation":
                cites = parse_citations(text)
                offending = [c for c in cites
                             if c[0] == spec["book"] and c[1] == spec["article"]]
                per_run.append(not offending)
                if offending:
                    details.append(f"forbidden citation present: {offending}")
            else:
                raise ValueError(f"{cid}: unknown check type {check!r}")

        name = {
            "require": f"require /{spec.get('pattern', '')}/",
            "require_any": "require any of "
                           + " | ".join(spec.get("patterns", []))[:60],
            "forbid": f"forbid /{spec.get('pattern', '')}/",
            "require_citation": f"cite {spec.get('book')} Art {spec.get('article')}",
            "forbid_citation": f"never cite {spec.get('book')} Art {spec.get('article')}",
        }[check]
        out.append(Result(cid, bucket, name, status, per_run,
                          detail="; ".join(details[:2]), finding=finding))

    # --- auto-checks on every generated answer -------------------------------
    auto = config.get("auto_checks", {})
    threshold = int(config.get("verbatim_threshold", 25))

    if "citations_supported" in auto:
        per_run, details = [], []
        for text, docs in zip(answers, docs_per_run):
            bad = graph.unsupported_citations(text, graph.allowed_citations(docs))
            per_run.append(not bad)
            if bad:
                details.append(f"unsupported: {bad}")
        spec = auto["citations_supported"]
        out.append(Result(cid, bucket, "auto: citations supported by evidence",
                          spec.get("status", "must_pass"), per_run,
                          detail="; ".join(details[:2]),
                          finding=spec.get("finding", "")))

    if "hedges_attributable" in auto:
        per_run, details = [], []
        for text, docs in zip(answers, docs_per_run):
            flagged = unattributable_hedges(text, docs)
            per_run.append(not flagged)
            if flagged:
                details.append(f"unattributable hedges: {flagged}")
        spec = auto["hedges_attributable"]
        out.append(Result(cid, bucket, "auto: no unattributable hedges",
                          spec.get("status", "must_pass"), per_run,
                          detail="; ".join(details[:2]),
                          finding=spec.get("finding", "")))

    if "verbatim_max_run" in auto:
        per_run, details = [], []
        for text, docs in zip(answers, docs_per_run):
            run, where = longest_verbatim_run(text, docs)
            per_run.append(run <= threshold)
            details.append(f"{run}w vs {where}" if run > threshold else f"{run}w")
        spec = auto["verbatim_max_run"]
        out.append(Result(cid, bucket, f"auto: verbatim run <= {threshold} words",
                          spec.get("status", "known_fail"), per_run,
                          detail="; ".join(details), finding=spec.get("finding", "")))
    return out


# ---------------------------------------------------------------------------
# Cost estimate for the generation pass (tiktoken, before any generation call)
# ---------------------------------------------------------------------------

def estimate_generation_usd(cases: list[dict], retrieved: dict, runs: int,
                            model: str) -> float:
    import tiktoken
    try:
        encoder = tiktoken.encoding_for_model(model)
    except KeyError:
        encoder = tiktoken.get_encoding("o200k_base")
    rate_in, rate_out = graph.CHAT_PRICE_PER_1M.get(model, (0.15, 0.60))

    total = 0.0
    for case in cases:
        _game, _routed, docs, scope, note = retrieved[case["id"]]
        books = "; ".join(f"{t} ({n} excerpt{'s' if n != 1 else ''})"
                          for t, n in graph.books_in_evidence(docs))
        user = graph.USER.format(question=case["question"], scope=scope, books=books,
                                 query=case["question"], note=note,
                                 index=graph.index_lines(docs),
                                 context=graph.render(docs))
        tokens_in = len(encoder.encode(graph.SYSTEM)) + len(encoder.encode(user))
        per_call = (tokens_in * rate_in + EST_OUTPUT_TOKENS * rate_out) / 1e6
        per_case = per_call * RETRY_FACTOR * runs
        if case.get("route") == "auto":
            per_case += runs * (ROUTER_EST[0] * rate_in + ROUTER_EST[1] * rate_out) / 1e6
        total += per_case
    return total


def actual_usd(usages: list[dict], model: str) -> float:
    rate_in, rate_out = graph.CHAT_PRICE_PER_1M.get(model, (0.0, 0.0))
    tin = sum(u.get("input", 0) for u in usages)
    tout = sum(u.get("output", 0) for u in usages)
    return (tin * rate_in + tout * rate_out) / 1e6


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

BUCKET_ORDER = ["conflict", "cross-scope", "normal", "pipeline", "regression"]


def report(results: list[Result], runs: int, generated: bool) -> bool:
    by_case: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for res in results:
        by_case[(res.bucket, res.case)].append(res)

    buckets = sorted({b for b, _ in by_case},
                     key=lambda b: (BUCKET_ORDER.index(b)
                                    if b in BUCKET_ORDER else 99))
    all_musts_ok = True
    tallies: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for bucket in buckets:
        print(f"\n== bucket: {bucket} ==")
        for (b, case), rows in sorted(by_case.items()):
            if b != bucket:
                continue
            musts = [r for r in rows if r.status == "must_pass"]
            knowns = [r for r in rows if r.status == "known_fail"]
            failed = [r for r in musts if not r.ok]
            confirmed = [r for r in knowns if r.confirmed]
            surprising = [r for r in knowns if not r.confirmed]

            if failed:
                verdict = "FAIL"
                tallies[bucket]["fail"] += 1
                all_musts_ok = False
            else:
                verdict = "PASS"
                tallies[bucket]["pass"] += 1
            if confirmed:
                tallies[bucket]["known_fail_confirmed"] += 1

            flags = ""
            if confirmed:
                flags += f"  [{len(confirmed)} known_fail confirmed]"
            if surprising:
                flags += f"  [{len(surprising)} known_fail NOW PASSING]"
            print(f"  [{verdict}] {case}  "
                  f"({len(musts) - len(failed)}/{len(musts)} must){flags}")

            for r in failed:
                print(f"      FAIL      {r.name}"
                      f"  runs={['P' if p else 'F' for p in r.passed_runs]}")
                if r.detail:
                    print(f"                {r.detail[:300]}")
            for r in confirmed:
                print(f"      KNOWN_FAIL {r.name}"
                      f"  runs={['P' if p else 'F' for p in r.passed_runs]}")
                if r.finding:
                    print(f"                -> {r.finding}")
                if r.detail:
                    print(f"                {r.detail[:300]}")
            for r in surprising:
                print(f"      NOTICE    known_fail NOW PASSING in all {runs} runs: "
                      f"{r.name}")
                if r.finding:
                    print(f"                was -> {r.finding}")

    print("\n== summary ==")
    for bucket in buckets:
        t = tallies[bucket]
        print(f"  {bucket:12s} pass={t['pass']:3d} fail={t['fail']:3d} "
              f"cases_with_confirmed_known_fail={t['known_fail_confirmed']}")
    if not generated:
        print("  (generation checks skipped -- retrieval-only mode)")
    print(f"\nEVAL {'PASS' if all_musts_ok else 'FAIL'} "
          f"(gate: every must_pass assertion, in every run)")
    return all_musts_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--retrieval-only", action="store_true",
                        help="offline pins + retrieval checks only; no generation")
    parser.add_argument("--runs", type=int, default=None,
                        help="generation repetitions per case (default: config.runs)")
    parser.add_argument("--max-usd", type=float, default=0.50,
                        help="refuse the generation pass above this estimate")
    parser.add_argument("--only", nargs="*", default=None, help="case ids to run")
    parser.add_argument("--bucket", nargs="*", default=None, help="buckets to run")
    parser.add_argument("--show-answers", action="store_true",
                        help="print every generated answer (debugging)")
    parser.add_argument("--queries", type=Path, default=QUERIES,
                        help="alternate query set (harness self-tests)")
    args = parser.parse_args(argv)

    spec = yaml.safe_load(args.queries.read_text())
    config = spec.get("config", {})
    runs = args.runs or int(config.get("runs", 2))

    cases = spec["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]
    if args.bucket:
        cases = [c for c in cases if c["bucket"] in set(args.bucket)]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    results: list[Result] = []
    usages: list[dict] = []

    # Phase 0: offline pins (skipped under --only/--bucket filters unless included).
    if not args.only and (not args.bucket or "regression" in args.bucket):
        results += offline_checks(spec.get("regression", {}))

    # Phase 1: retrieval (query embeddings; router only where route: auto).
    print(f"retrieval phase: {len(cases)} cases "
          f"({sum(1 for c in cases if c.get('route') == 'auto')} need a router call)")
    retrieved: dict[str, tuple] = {}
    for case in cases:
        game, routed, docs, scope, note = resolve_case(case, usages)
        retrieved[case["id"]] = (game, routed, docs, scope, note)
        results += retrieval_checks(case, routed, docs)

    # Phase 2: generation, budget-guarded.
    generated = False
    if not args.retrieval_only:
        gen_cases = [c for c in cases if c.get("generate")]
        if gen_cases:
            model = graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
            est = estimate_generation_usd(gen_cases, retrieved, runs, model)
            print(f"\ngeneration phase: {len(gen_cases)} cases x {runs} runs on {model}")
            print(f"  ESTIMATED COST ${est:.4f} "
                  f"(tiktoken prompt tokens, x{RETRY_FACTOR} retry factor, "
                  f"{EST_OUTPUT_TOKENS} est output tokens)")
            if est > args.max_usd:
                print(f"  ESTIMATE EXCEEDS --max-usd ${args.max_usd:.4f}. Refusing "
                      "the generation pass. Re-run with a higher ceiling if intended.")
                return 2
            import os
            if not os.getenv("OPENAI_API_KEY"):
                print("  OPENAI_API_KEY is not set; cannot generate.", file=sys.stderr)
                return 2

            for case in gen_cases:
                answers, docs_per_run = [], []
                for i in range(runs):
                    state = graph.ask(case["question"], game=case.get("game"))
                    answers.append(state.get("answer", ""))
                    docs_per_run.append(state.get("docs") or [])
                    usages.extend(state.get("usage") or [])
                    if args.show_answers:
                        print(f"\n--- {case['id']} run {i + 1} ---\n"
                              f"{state.get('answer', '')}\n")
                print(f"  generated {case['id']} x{runs}")
                results += answer_checks(case, answers, docs_per_run, config)
            generated = True

    ok = report(results, runs, generated)

    model = graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    spent = actual_usd(usages, model)
    tin = sum(u.get("input", 0) for u in usages)
    tout = sum(u.get("output", 0) for u in usages)
    print(f"\nmeasured chat spend: ${spent:.4f} ({tin:,} in / {tout:,} out tokens "
          f"on {model}; query embeddings add ~$0.000001/case)")
    print("determinism note: generation is unseeded (A2); must_pass = pass in "
          f"EVERY of {runs} runs, known_fail confirmed if failed in ANY run.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Benchmark entry point.

    python -m benchmark.run
    python -m benchmark.run --gate-stability 10 --determinism-probe

**Exit codes: 0 unless INFRASTRUCTURE failed.** Infrastructure failure is exactly
three things — the live corpus does not match `config.yaml`'s fingerprint pin,
more than 20% of queries raised, or a `must_include` label matches no chunk. It
NEVER exits non-zero on a metric value. `eval/run.py` is the only build gate;
two gates means pressure to weaken the numeric one, and a threshold is tunable in
a way `all(passed_runs)` is not.

Stage 0 + Stage 1 only. The generation tier (`--generate`) is Stage 3 and is not
enabled here: `metrics/precedence.py` and `metrics/faithfulness.py` do not exist
yet, and reporting generation-side numbers without them would be partial in a way
the reader could not see.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import graph  # noqa: E402

from benchmark import pipeline, qrels as qrels_mod  # noqa: E402
from benchmark.metrics import abstention, citation, latency, retrieval  # noqa: E402
from benchmark.record import Measurement  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.yaml"
OVERLAY = HERE / "queries" / "overlay.yaml"
QUERIES = ROOT / "eval" / "queries.yaml"

EXIT_OK = 0
EXIT_INFRASTRUCTURE = 2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_fingerprint() -> str:
    """First 8 hex of chunks.pkl's sha256 — the same definition server.py:343
    uses. Recomputed here rather than imported, because importing `server`
    would pull in starlette and a sqlite connection for a hash."""
    return sha256(ROOT / graph._env("EWC_DATA_DIR", "data") / "chunks.pkl")[:8]


def load_eval_module():
    """Load `eval/run.py` by path. `eval/` has no `__init__.py`, so it is not
    importable as a package; this is the same reason `/benchmark` imports `graph`
    directly rather than importing anything from `eval`."""
    spec = importlib.util.spec_from_file_location("_ewc_eval_run", ROOT / "eval" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Baseline A extras
# ---------------------------------------------------------------------------

def gate_stability(runs: int, cases: list[dict], spec: dict):
    """Run `eval/run.py`'s RETRIEVAL assertions N times; per-assertion pass rate.

    Drives `eval/run.py`'s own functions (`offline_checks`, `resolve_case`,
    `retrieval_checks`) rather than parsing its stdout, so the result is
    per-ASSERTION and not per-case. Nothing is monkeypatched and no assertion is
    reinterpreted — these are the gate's own `Result` objects.

    This measures the RETRIEVAL half of the gate only. Log 009's B-1 ("~47% at
    the shipped default") is a GENERATION assertion — `conflict-vac-six-year`'s
    precedence-statement requirement. A stable 1.0 here does NOT refute B-1; it
    localises it.
    """
    ev = load_eval_module()
    tally: dict[tuple[str, str], list[bool]] = defaultdict(list)
    run_ok: list[bool] = []
    usages: list[dict] = []
    for _ in range(runs):
        results = list(ev.offline_checks(spec.get("regression", {})))
        for case in cases:
            game, routed, docs, scope, note = ev.resolve_case(case, usages)
            results += ev.retrieval_checks(case, routed, docs)
        ok = True
        for res in results:
            if res.status != "must_pass":
                continue
            tally[(res.case, res.name)].append(res.ok)
            ok = ok and res.ok
        run_ok.append(ok)

    rows = []
    for (case_id, name), outcomes in sorted(tally.items()):
        rate = sum(outcomes) / len(outcomes)
        rows.append({"case_id": case_id, "assertion": name, "runs": len(outcomes),
                     "pass_rate": rate, "outcomes": ["P" if o else "F" for o in outcomes]})
    unstable = [r for r in rows if 0.0 < r["pass_rate"] < 1.0]
    always_fail = [r for r in rows if r["pass_rate"] == 0.0]

    model = graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    spend = ev.actual_usd(usages, model)

    measurements = [
        Measurement(
            name="gate_stability_whole_run", value=None,
            per_run=[1.0 if o else 0.0 for o in run_ok], n=len(run_ok),
            unit="probability",
            basis=(f"fraction of {runs} independent executions of eval/run.py's "
                   "RETRIEVAL + offline-pin must_pass assertions in which every one "
                   "held. GENERATION assertions are NOT included — log 009's B-1 "
                   "'~47% at runs: 3' is a generation assertion "
                   "(conflict-vac-six-year's precedence statement) and is not "
                   "measured here. A 1.0 localises B-1, it does not refute it."),
        ),
        Measurement(
            name="gate_assertion_pass_rate_mean", value=None,
            per_run=[r["pass_rate"] for r in rows], n=len(rows), unit="probability",
            basis=(f"mean per-assertion pass rate over {len(rows)} distinct "
                   f"must_pass retrieval/offline assertions x {runs} runs. One "
                   "observation per ASSERTION (its own pass rate), so the stdev is "
                   "spread across assertions, not run-to-run noise."),
        ),
        Measurement(
            name="gate_unstable_assertions", value=float(len(unstable)),
            per_run=[float(len(unstable))], n=1, unit="count",
            basis=(f"count of assertions with a pass rate strictly between 0 and 1 "
                   f"across {runs} runs — i.e. genuinely flaky rather than broken. "
                   f"Assertions that failed in every run are counted separately "
                   f"({len(always_fail)})."),
        ),
    ]
    detail = {"runs": runs, "assertions": rows, "unstable": unstable,
              "always_fail": always_fail, "per_run_whole_gate": run_ok,
              "measured_chat_spend_usd": spend}
    return measurements, detail


def determinism_probe(case: dict, runs: int):
    """One query, N times, chunk_id SETS and RANK MAPS diffed.

    The cost model asserts retrieval is deterministic given a fixed index. This
    verifies it rather than assuming it — dense retrieval goes through an OpenAI
    embedding call and an HNSW graph, neither of which is contractually
    bit-stable.
    """
    observations = []
    for _ in range(runs):
        record = pipeline.run_case(case, generate=False)
        observations.append({
            "chunk_ids_ordered": record.chunk_ids,
            "chunk_id_set": sorted(record.chunk_ids),
            "ranks": dict(record.ranks),
            "cost_usd": record.cost_usd,
        })
    first = observations[0]
    same_set = [o["chunk_id_set"] == first["chunk_id_set"] for o in observations]
    same_ranks = [o["ranks"] == first["ranks"] for o in observations]
    same_order = [o["chunk_ids_ordered"] == first["chunk_ids_ordered"] for o in observations]
    measurements = [
        Measurement(
            name="retrieval_determinism_pool", value=None,
            per_run=[1.0 if s else 0.0 for s in same_set], n=len(same_set),
            unit="ratio",
            basis=(f"fraction of {runs} repeats of `{case['id']}` returning the same "
                   "SET of chunk_ids as the first repeat (the first repeat is "
                   "included and is trivially 1.0). Probes embedding + HNSW "
                   "stability, which the cost model assumes but nothing guarantees."),
        ),
        Measurement(
            name="retrieval_determinism_ranks", value=None,
            per_run=[1.0 if s else 0.0 for s in same_ranks], n=len(same_ranks),
            unit="ratio",
            basis=(f"as above but comparing the full chunk_id -> relevance-rank map. "
                   "Strictly stronger than pool identity: the same 8 chunks in a "
                   "different fused order would fail here and pass there."),
        ),
    ]
    detail = {"case_id": case["id"], "runs": runs,
              "identical_pool": all(same_set), "identical_ranks": all(same_ranks),
              "identical_authority_order": all(same_order),
              "observations": observations}
    return measurements, detail


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_report(summary: dict, groups: dict[str, list[Measurement]]) -> str:
    out = ["# Benchmark report", ""]
    out.append(f"- run: `{summary['run_id']}`")
    out.append(f"- corpus fingerprint: `{summary['integrity']['corpus_fingerprint']}` "
               f"(pinned `{summary['integrity']['corpus_fingerprint_pin']}`)")
    for name, digest in summary["integrity"]["sha256"].items():
        out.append(f"- sha256 `{name}`: `{digest}`")
    out.append(f"- tier: {summary['tier']}  ·  measured spend "
               f"${summary['spend_usd']:.6f}")
    out.append("")
    out.append("> Every number below carries a `basis`. Read it. "
               "Precision@k / NDCG / MAP / bpref are NOT here: the only labels are "
               "30 positive-only, partial `must_include` entries, so an unlabelled "
               "retrieved chunk is unknown-relevance, not irrelevant. Stage 2 "
               "pool judging unlocks them.")
    out.append("")
    for group, measurements in groups.items():
        out.append(f"## {group}")
        out.append("")
        out.append("| metric | value | basis |")
        out.append("|---|---|---|")
        for m in measurements:
            out.append(f"| `{m.name}` | {m.render()} | {m.basis} |")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gate-stability", type=int, default=None,
                        help="run eval/run.py's retrieval assertions N times "
                             "(default: config.runs.gate_stability_runs)")
    parser.add_argument("--determinism-probe", action="store_true", default=None,
                        help="run one query N times and diff the chunk_id sets")
    parser.add_argument("--no-determinism-probe", dest="determinism_probe",
                        action="store_false")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--only", nargs="*", default=None, help="case ids to run")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    config = yaml.safe_load(CONFIG.read_text())
    overlay = yaml.safe_load(OVERLAY.read_text())["cases"]

    # ---- integrity, BEFORE spending -------------------------------------
    queries_sha_before = sha256(QUERIES)
    live_fp = corpus_fingerprint()
    pin_fp = config["corpus"]["fingerprint"]
    print(f"corpus fingerprint  live={live_fp}  pinned={pin_fp}")
    if live_fp != pin_fp:
        print("\nINFRASTRUCTURE FAILURE: the live corpus does not match the pin in "
              "benchmark/config.yaml. Refusing to spend. Every number produced "
              "against a different index describes a different system — this is "
              "the exact failure that produced log 010's B-1.", file=sys.stderr)
        return EXIT_INFRASTRUCTURE

    shape = pipeline.assert_linear_graph()
    print(f"graph shape         {' -> '.join(['route','retrieve','resolve','answer'])} "
          f"(asserted, {len(shape['conditional_edges'])} conditional edges)")

    geometry = {"dense_k": graph.DENSE_K, "lexical_k": graph.LEXICAL_K,
                "fused_k": graph.FUSED_K, "rrf_k": graph.RRF_K,
                "accountable_rank": graph.ACCOUNTABLE_RANK}
    drift = {k: (v, config["retrieval"].get(k)) for k, v in geometry.items()
             if config["retrieval"].get(k) != v}
    if drift:
        print(f"NOTE: config.yaml disagrees with graph.py on {drift}. "
              "Using graph.py's values; config.yaml is documentation.")

    spec = yaml.safe_load(QUERIES.read_text())
    cases = spec["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]
    cases_by_id = {c["id"]: c for c in cases}

    try:
        labels = qrels_mod.build_labels(cases)
    except qrels_mod.UnparseableQrels as exc:
        print(f"\nINFRASTRUCTURE FAILURE: {exc}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE

    # ---- Stage 0/1 free tier --------------------------------------------
    router_runs = int(config["runs"]["free_tier_router_cases"])
    router_cases = [c for c in cases if c.get("route") == "auto"]
    print(f"\nfree tier: {len(cases)} cases at N=1, of which {len(router_cases)} "
          f"`route: auto` repeat at N={router_runs}")

    records = []
    router_repeats: dict[str, list] = {}
    doc_objects: dict[str, list] = {}
    for n, case in enumerate(cases, start=1):
        record = pipeline.run_case(case, generate=False)
        records.append(record)
        status = "ERROR" if record.error else f"{len(record.docs)} docs"
        print(f"  [{n:2d}/{len(cases)}] {case['id']:44s} {status}")
        if case.get("route") == "auto":
            outputs = [record.routed]
            for _ in range(router_runs - 1):
                extra = pipeline.run_case(case, generate=False)
                outputs.append(extra.routed)
                # The repeat is NOT appended to `records`: it would double-count
                # this case in every per-case metric. Only its cost is carried.
                record.cost_usd += extra.cost_usd
            router_repeats[case["id"]] = outputs

    errored = [r for r in records if r.error]
    if len(errored) > 0.20 * max(1, len(records)):
        print(f"\nINFRASTRUCTURE FAILURE: {len(errored)}/{len(records)} queries "
              "errored (>20%). Refusing to publish metrics computed over a broken "
              f"run. First error: {errored[0].error}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE

    # ---- ranks vs docs order --------------------------------------------
    mixed = [r for r in records
             if not r.error and len({d["authority"] for d in r.docs}) > 1]
    ranks_proof = (pipeline.assert_ranks_are_not_docs_order(mixed[0])
                   if mixed else {"conclusive": False,
                                  "note": "no mixed-authority pool in this run"})
    conclusive = [pipeline.assert_ranks_are_not_docs_order(r) for r in mixed]
    ranks_proof_summary = {
        "mixed_authority_cases": len(mixed),
        "cases_where_orders_differ": sum(1 for c in conclusive if c["orders_differ"]),
        "example": ranks_proof,
    }

    # ---- metrics ---------------------------------------------------------
    groups: dict[str, list[Measurement]] = {}
    details: dict = {}

    leak_m, leak_d = retrieval.leakage(records, cases_by_id)
    pure_m, pure_d = retrieval.scope_purity(records, cases_by_id)
    route_m, route_d = retrieval.router_accuracy(records, cases_by_id)
    stab_m, stab_d = retrieval.router_stability(router_repeats, cases_by_id)
    groups["Baseline A — scope, routing, leakage"] = [leak_m, pure_m, route_m, stab_m]
    details["leakage"] = leak_d
    details["scope_purity"] = pure_d
    details["router"] = {"accuracy": route_d, "stability": stab_d}

    lat_m, lat_d = latency.node_latency(records)
    cost_m, cost_d = latency.cost(records, tier="free")
    groups["Baseline A — latency and cost"] = lat_m + cost_m
    details["latency"] = lat_d
    details["cost"] = cost_d

    abst_m, abst_d = abstention.outcome_distribution(records, overlay)
    cite_m, cite_d = citation.validity_and_coverage(records, doc_objects)
    mis_m, mis_d = citation.misattribution(records, doc_objects)
    groups["Baseline A — generation tier (NOT RUN at Stage 0/1)"] = abst_m + cite_m + mis_m
    details["abstention"] = abst_d
    details["citation"] = {"validity_coverage": cite_d, "misattribution": mis_d}

    rec_m, rec_d = retrieval.judged_recall(records, labels, config["retrieval"]["cutoffs"],
                                           graph.ACCOUNTABLE_RANK)
    groups["Baseline B — judged retrieval (30 must_include labels)"] = rec_m
    details["judged_recall"] = rec_d
    details["qrels"] = qrels_mod.summarise(labels)

    trec_qrels = qrels_mod.trec_qrels(labels)
    trec_run = qrels_mod.trec_run(records, graph.FUSED_K)
    cross = retrieval.pytrec_cross_check(
        trec_qrels, trec_run, config["retrieval"]["cutoffs"])
    details["pytrec_eval"] = cross

    # The in-house figures are the ones reported; this proves they agree with the
    # real trec_eval C implementation rather than asking the reader to trust
    # hand-rolled arithmetic. A disagreement is recorded, not hidden.
    by_name = {m.name: m for ms in groups.values() for m in ms}
    agreement = {}
    if cross.get("available"):
        pairs = [("mrr", "recip_rank")]
        pairs += [(f"judged_recall_chunk_macro@{k}", f"recall_{k}")
                  for k in config["retrieval"]["cutoffs"]]
        for ours, theirs in pairs:
            mine = by_name[ours].value if ours in by_name else None
            trec = cross.get(theirs)
            agreement[f"{ours} vs pytrec {theirs}"] = {
                "in_house": mine, "pytrec_eval": trec,
                "abs_diff": (None if mine is None or trec is None
                             else abs(mine - trec)),
                "agree_1e_9": (mine is not None and trec is not None
                               and abs(mine - trec) < 1e-9),
            }
    details["pytrec_agreement"] = agreement

    # ---- optional probes -------------------------------------------------
    gate_runs = (args.gate_stability if args.gate_stability is not None
                 else int(config["runs"]["gate_stability_runs"]))
    if gate_runs and not args.only:
        print(f"\ngate stability: {gate_runs} x eval/run.py retrieval assertions")
        gm, gd = gate_stability(gate_runs, cases, spec)
        groups["Baseline A — gate stability"] = gm
        details["gate_stability"] = gd
    else:
        details["gate_stability"] = {"skipped": True}

    probe = config["runs"]["determinism_probe_case"]
    want_probe = True if args.determinism_probe is None else args.determinism_probe
    if want_probe and probe in cases_by_id:
        n = int(config["runs"]["determinism_probe_runs"])
        print(f"determinism probe: {n} x `{probe}`")
        dm, dd = determinism_probe(cases_by_id[probe], n)
        groups["Baseline A — embedding determinism"] = dm
        details["determinism"] = dd
    else:
        details["determinism"] = {"skipped": True}

    # ---- integrity, AFTER --------------------------------------------------
    queries_sha_after = sha256(QUERIES)
    spend = sum(r.cost_usd for r in records)
    spend += details.get("gate_stability", {}).get("measured_chat_spend_usd", 0.0) or 0.0
    spend += sum(o["cost_usd"] for o in details.get("determinism", {})
                 .get("observations", []))

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = args.out_dir or (HERE / "results" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "run_id": run_id,
        "tier": "free (retrieval + offline; generation NOT run)",
        "stages": ["0", "1"],
        "spend_usd": spend,
        "elapsed_s": time.perf_counter() - started,
        "integrity": {
            "corpus_fingerprint": live_fp,
            "corpus_fingerprint_pin": pin_fp,
            "sha256": {
                "graph.py": sha256(ROOT / "graph.py"),
                "eval/run.py": sha256(ROOT / "eval" / "run.py"),
                "eval/queries.yaml": queries_sha_before,
                "data/chunks.pkl": sha256(ROOT / "data" / "chunks.pkl"),
            },
            "eval_queries_unchanged": queries_sha_before == queries_sha_after,
            "graph_shape": shape,
            "retrieval_geometry_from_graph_py": geometry,
            "config_geometry_drift": drift,
            "pool_v1_labels": None,
        },
        "ranks_vs_docs_order": ranks_proof_summary,
        "pytrec_agreement": agreement,
        "rank_histogram": rec_d["rank_histogram"],
        "cases": len(cases),
        "errored_cases": [{"case_id": r.case_id, "error": r.error} for r in errored],
        "metrics": {
            group: [m.to_dict() for m in ms] for group, ms in groups.items()
        },
        "not_computed": {
            "precision@k / ndcg@8 / map / bpref": (
                "Requires relevance judgements over the retrieval pool. The only "
                "labels today are 30 positive-only, partial must_include entries; "
                "an unlabelled retrieved chunk is unknown-relevance, not "
                "irrelevant. Computing P@8 as 30 labels / 224 slots would be a "
                "labelling artefact read as a score. Unlocks at Stage 2."),
            "faithfulness": "Stage 4. Judge is gpt-4o and is gated on calibration.",
            "precedence correctness": "Stage 3 (metrics/precedence.py, not built).",
            "citation / abstention / misattribution": (
                "Implemented but NOT RUN: the generation tier is Stage 3."),
            "grade node latency": (
                "The node was never built. CLAUDE.md's contract is route -> "
                "retrieve -> grade -> (retrieve | resolve) -> answer; the shipped "
                "graph is route -> retrieve -> resolve -> answer. `tries` is dead "
                "state."),
        },
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (out_dir / "details.json").write_text(json.dumps(
        {"records": [r.to_dict() for r in records], **details}, indent=2, default=str))
    (out_dir / "report.md").write_text(render_report(summary, groups))

    # ---- console ---------------------------------------------------------
    print("\n" + "=" * 78)
    for group, measurements in groups.items():
        print(f"\n== {group} ==")
        for m in measurements:
            print(f"  {m.name:44s} {m.render()}")
    print("\n== integrity ==")
    print(f"  eval/queries.yaml unchanged           {summary['integrity']['eval_queries_unchanged']}")
    print(f"  corpus fingerprint                    {live_fp} (pinned {pin_fp})")
    print(f"  ranks != docs order (mixed authority) "
          f"{ranks_proof_summary['cases_where_orders_differ']}"
          f"/{ranks_proof_summary['mixed_authority_cases']} cases")
    print(f"  pytrec_eval agreement                 "
          f"{sum(1 for v in agreement.values() if v['agree_1e_9'])}"
          f"/{len(agreement)} figures match to 1e-9")
    print(f"  rank histogram (judged chunk hits)    "
          + " ".join(f"r{r}={rec_d['rank_histogram'][r]}"
                     for r in sorted(rec_d["rank_histogram"], key=int)))
    print(f"  measured spend                        ${spend:.6f}")
    print(f"  results                               {out_dir}")

    if not summary["integrity"]["eval_queries_unchanged"]:
        print("\nINFRASTRUCTURE FAILURE: eval/queries.yaml changed during the run.",
              file=sys.stderr)
        return EXIT_INFRASTRUCTURE
    print("\nbenchmark/run.py exits 0: no infrastructure failure. It does not gate "
          "on any metric value — eval/run.py is the only build gate.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

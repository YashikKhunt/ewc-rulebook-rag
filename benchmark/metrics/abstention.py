"""Abstention scoring: `state["outcome"]` crossed with overlay `answerable`.

`graph._outcome` (`graph.py:1567-1587`) is deliberately conservative and this
module inherits that conservatism rather than papering over it. It returns:

* ``answered``     the text carries at least one citation
* ``uncited``      the text carries NO citation at all
* ``no_evidence``  `answer` took the empty-pool branch
* ``withheld``     the mechanical post-checks could not reconcile the draft

`uncited` is a FACT ABOUT THE TEXT, not a claim that the system abstained. A
citation-free answer is either an abstention or a non-negotiable-#3 defect, and
which one it is cannot be decided mechanically. So this module never reports an
"abstention rate": it reports the joint distribution and names the cell that is
ambiguous. Collapsing `uncited` into "abstained" would score a #3 defect as a
success, which is the exact inversion this product cannot afford.

Generation tier only. On the free tier every record has an empty `outcome`, and
the measurements below are emitted with `n=0` and a basis saying so — an absent
number that says why it is absent, rather than a silent omission.
"""

from __future__ import annotations

from collections import Counter

from benchmark.record import Measurement

ABSTAINING = {"no_evidence", "withheld"}
AMBIGUOUS = {"uncited"}


def outcome_distribution(records, overlay) -> tuple[list[Measurement], dict]:
    generated = [r for r in records if r.outcome and not r.error]
    counts = Counter(r.outcome for r in generated)
    joint: Counter = Counter()
    rows = []
    for record in generated:
        answerable = (overlay.get(record.case_id) or {}).get("answerable")
        joint[(answerable, record.outcome)] += 1
        rows.append({"case_id": record.case_id, "answerable": answerable,
                     "outcome": record.outcome})

    detail = {
        "n_generated": len(generated),
        "outcome_counts": dict(counts),
        "joint_answerable_x_outcome": {f"{a}|{o}": n for (a, o), n in joint.items()},
        "rows": rows,
        "note": ("`uncited` is intentionally NOT counted as an abstention. It is a "
                 "fact about the text (no citation present); whether it is an "
                 "abstention or a non-negotiable-#3 defect is not mechanically "
                 "decidable and is not guessed here."),
    }

    if not generated:
        return [Measurement(
            name="outcome_distribution", value=None, per_run=[], n=0, unit="count",
            basis=("NOT MEASURED: the generation tier did not run. `outcome` is "
                   "produced by `graph.answer`, which the free tier never calls. "
                   "This is an absent measurement, not a zero."),
        )], detail

    measurements = []
    unanswerable = [r for r in generated
                    if (overlay.get(r.case_id) or {}).get("answerable") is False]
    answerable = [r for r in generated
                  if (overlay.get(r.case_id) or {}).get("answerable") is True]

    vals = [1.0 if r.outcome in ABSTAINING else 0.0 for r in unanswerable]
    measurements.append(Measurement(
        name="abstained_on_unanswerable", value=None, per_run=vals, n=len(vals),
        unit="ratio",
        basis=(f"fraction of the {len(vals)} cases the overlay marks "
               "`answerable: false` where `outcome` was `no_evidence` or "
               "`withheld`. `uncited` is EXCLUDED from the numerator: it may be an "
               "abstention or a missing-citation defect and the two are not "
               "mechanically separable."),
    ))
    vals = [1.0 if r.outcome in ABSTAINING else 0.0 for r in answerable]
    measurements.append(Measurement(
        name="abstained_on_answerable", value=None, per_run=vals, n=len(vals),
        unit="ratio",
        basis=(f"false-abstention rate: fraction of the {len(vals)} cases marked "
               "`answerable: true` where the system refused. Lower is better; this "
               "is the cost side of abstention-as-a-success-state."),
    ))
    vals = [1.0 if r.outcome in AMBIGUOUS else 0.0 for r in generated]
    measurements.append(Measurement(
        name="uncited_rate", value=None, per_run=vals, n=len(vals), unit="ratio",
        basis=(f"fraction of the {len(vals)} generated answers carrying NO citation "
               "at all. Deliberately reported on its own rather than folded into "
               "either abstention or failure — see graph.py:1567-1587."),
    ))
    return measurements, detail

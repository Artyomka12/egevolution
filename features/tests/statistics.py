"""Pure test-result ranking, separate from legacy EGE aggregates."""


def best_attempt(attempts):
    """Return the best fully graded attempt, or None.

    Each attempt supplies its raw UTC-millisecond submitted_at, id, state and
    a summary from grading.summarize. Scores are compared as exact fractions;
    rounded percentages never participate. Equal fractions prefer the latest
    submission, then the largest ID. No student access rights are implied by
    returning a historical best: latest-attempt guards remain mandatory.
    """
    best = None
    for attempt in attempts:
        if attempt["state"] != "graded":
            continue
        summary = attempt["summary"]
        if not summary["is_final"] or summary["pending_count"]:
            continue
        earned, total = summary["earned"], summary["total"]
        if (type(earned) is not int or type(total) is not int
                or total < 1 or earned < 0 or earned > total):
            raise ValueError("Invalid result fraction")
        if best is None:
            best = attempt
            continue
        previous = best["summary"]
        comparison = earned * previous["total"] - previous["earned"] * total
        if comparison > 0 or (comparison == 0 and
                (attempt["submitted_at"], attempt["id"]) >
                (best["submitted_at"], best["id"])):
            best = attempt
    return best

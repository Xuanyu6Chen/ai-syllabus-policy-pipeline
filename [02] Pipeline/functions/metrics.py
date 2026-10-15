# The calculations for the Test section of the runner: how much of the hand-copied policy text a chunk contains,
# and how well the model's probabilities agree with the hand-coded labels. Nothing here is specific to one model.

import re

import numpy
import pandas


# ============================================================ 1. does the chunk contain the policy?

def capture(text, gold_text, piece=5):
    """The share of the hand-copied policy text that `text` contains. The copied text is cut into overlapping
    pieces of 5 words; the answer is the share of those pieces found in `text` (1.0 = all of it)."""
    gold_words = re.findall(r"[a-z0-9]+", gold_text.lower())
    if not gold_words:
        return None
    haystack = " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "
    found = 0
    total = max(1, len(gold_words) - piece + 1)
    for start in range(total):
        if " " + " ".join(gold_words[start:start + piece]) + " " in haystack:
            found = found + 1
    return found / total


def chunk_check(rows):
    """For each hand-coded policy syllabus: how much of the copied policy text is in the file, and in the chunk.
    Only syllabi whose copied text really is in the file (95% or more) can judge the chunker."""
    lines = []
    for row in rows:
        if row.get("gold_policy_found") != 1 or not row.get("gold_text"):
            continue
        in_file = capture(row["text"], row["gold_text"])
        in_chunk = capture(row["chunk"], row["gold_text"])
        if in_file < 0.95:
            verdict = "cannot judge"
        elif in_chunk >= 0.95:
            verdict = "full"
        elif in_chunk >= 0.05:
            verdict = "partial"
        else:
            verdict = "missed"
        lines.append({"id": row["id"], "university": row["university"], "in_file": round(in_file, 2),
                      "in_chunk": round(in_chunk, 2), "chunk_chars": row["chunk_chars"], "verdict": verdict})
    return pandas.DataFrame(lines)


# ============================================================ 2. how good are the model's probabilities?

def auroc(y, p):
    """The chance that a real "yes" gets a higher probability than a real "no" (a tie counts half).
    0.5 = no better than a coin, 1.0 = perfect. None when there is no "yes" or no "no" to compare."""
    yes = p[y == 1]
    no = p[y == 0]
    if len(yes) == 0 or len(no) == 0:
        return None
    wins = 0.0
    for value in yes:
        wins = wins + (value > no).sum() + 0.5 * (value == no).sum()
    return wins / (len(yes) * len(no))


def auroc_range(y, p, repeats=500):
    """A 95% range for the AUROC: redraw the same number of syllabi at random (with repeats) 500 times."""
    random = numpy.random.default_rng(0)
    values = []
    for repeat in range(repeats):
        picks = random.integers(0, len(y), len(y))
        value = auroc(y[picks], p[picks])
        if value is not None:
            values.append(value)
    if len(values) < repeats / 2:
        return None, None
    return float(numpy.percentile(values, 2.5)), float(numpy.percentile(values, 97.5))


def auprc(y, p):
    """Average precision: walk down from the highest probability and average the precision at each real "yes".
    Compare it with the base rate (the share of "yes"), which is what guessing scores."""
    if y.sum() == 0:
        return None
    order = numpy.argsort(-p, kind="stable")
    y_sorted = y[order]
    precision = numpy.cumsum(y_sorted) / (numpy.arange(len(y)) + 1)
    return float(precision[y_sorted == 1].mean())


def counts_at(y, p, cutoff):
    """At one cutoff: right yes, wrong yes, missed yes."""
    said_yes = p >= cutoff
    right_yes = int((said_yes & (y == 1)).sum())
    wrong_yes = int((said_yes & (y == 0)).sum())
    missed_yes = int((~said_yes & (y == 1)).sum())
    return right_yes, wrong_yes, missed_yes


def precision_recall_f1(right_yes, wrong_yes, missed_yes):
    precision = right_yes / (right_yes + wrong_yes) if right_yes + wrong_yes else None
    recall = right_yes / (right_yes + missed_yes) if right_yes + missed_yes else None
    f1 = 2 * right_yes / (2 * right_yes + wrong_yes + missed_yes) if right_yes else 0.0
    return precision, recall, f1


def best_cutoff(y, p):
    """The cutoff with the highest F1 on these syllabi."""
    best_f1 = -1.0
    best = 0.5
    for cutoff in numpy.unique(p):
        f1 = precision_recall_f1(*counts_at(y, p, cutoff))[2]
        if f1 > best_f1:
            best_f1 = f1
            best = float(cutoff)
    return best


def _scorable(rows, field, na_counts_as_no):
    """The syllabi that can be scored on one field: their university, the hand-coded answer, and the model's probability.
    Policy Found is scored on every hand-coded syllabus; the other fields only where a policy exists."""
    universities, answers, probabilities = [], [], []
    for row in rows:
        if "gold_policy_found" not in row or row.get("p_" + field) is None:
            continue
        if field == "policy_found":
            answer = row["gold_policy_found"]
        else:
            if row["gold_policy_found"] != 1:
                continue
            answer = row.get("gold_" + field)
            if answer is None:                       # hand-coded "n/a" on a policy syllabus
                if not na_counts_as_no:
                    continue
                answer = 0
        universities.append(row["university"])
        answers.append(answer)
        probabilities.append(row["p_" + field])
    return numpy.array(universities), numpy.array(answers), numpy.array(probabilities, dtype=float)


def score(rows, fields, na_counts_as_no=False):
    """Two tables. By field: AUROC with its 95% range, AUPRC, and precision / recall / F1 when each university is
    held out (its cutoff is chosen on the other universities only). By university: the same held-out counts for each
    university."""
    by_field = []
    by_university = []
    for field in fields:
        universities, y, p = _scorable(rows, field, na_counts_as_no)
        line = {"field": field, "scored": len(y), "yes": int(y.sum())}
        if len(y) == 0:
            by_field.append(line)
            continue
        low, high = auroc_range(y, p)
        line.update({"base_rate": float(y.mean()), "auroc": auroc(y, p), "auroc_low": low, "auroc_high": high,
                     "auprc": auprc(y, p), "cutoff_all_universities": best_cutoff(y, p)})

        names = sorted(set(universities))
        if len(names) >= 2:
            totals = [0, 0, 0]
            for university in names:
                inside = universities == university
                cutoff = best_cutoff(y[~inside], p[~inside])
                right_yes, wrong_yes, missed_yes = counts_at(y[inside], p[inside], cutoff)
                totals = [totals[0] + right_yes, totals[1] + wrong_yes, totals[2] + missed_yes]
                by_university.append({"field": field, "university": university, "scored": int(inside.sum()),
                                      "yes": int(y[inside].sum()), "cutoff_from_other_universities": round(cutoff, 3),
                                      "right_yes": right_yes, "wrong_yes": wrong_yes, "missed_yes": missed_yes})
            precision, recall, f1 = precision_recall_f1(*totals)
            line.update({"heldout_precision": precision, "heldout_recall": recall, "heldout_f1": f1})
        by_field.append(line)
    if len(set(row["university"] for row in rows if "gold_policy_found" in row)) < 2:
        print("Only one university in this set, so nothing can be held out: the held-out columns are left out.")
    return pandas.DataFrame(by_field).round(3), pandas.DataFrame(by_university)


def cutoff_table(rows, fields, na_counts_as_no=False):
    """For each field and each cutoff from 0.05 to 0.95: how many syllabi get a "yes", and the precision, recall
    and F1 against the hand-coded labels. For Policy Found, 1 - recall is the share of real policies lost."""
    lines = []
    for field in fields:
        universities, y, p = _scorable(rows, field, na_counts_as_no)
        if len(y) == 0:
            continue
        for step in range(1, 20):
            cutoff = step / 20
            right_yes, wrong_yes, missed_yes = counts_at(y, p, cutoff)
            precision, recall, f1 = precision_recall_f1(right_yes, wrong_yes, missed_yes)
            lines.append({"field": field, "cutoff": cutoff, "said_yes": right_yes + wrong_yes, "right_yes": right_yes,
                          "wrong_yes": wrong_yes, "missed_yes": missed_yes, "precision": precision, "recall": recall,
                          "f1": f1})
    return pandas.DataFrame(lines).round(3)


# ============================================================ 3. step 4b: CS / BP per region

def region_comparison(rows, na_counts_as_no=False):
    """Step 4b against step 4, for CS and BP, on the hand-coded syllabi that have both:
    - AUROC from the whole chunk (step 4) and from the highest region (4b). The highest region is only a way to
      score 4b here; how region answers become the syllabus's answer is decided later.
    - On policies with 2 or more regions whose copied text sits in one region: is the region Kev scores highest
      the region that holds the coder's copied text?
    - On 1-region chunks: how far 4b's answer is from step 4's (the same text, so it should be close)."""
    lines = []
    for field, short in [("cs_present", "cs"), ("bp_present", "bp")]:
        both = [row for row in rows if row.get("p_" + short + "_regions") and row.get("p_" + field) is not None]
        highest = [dict(row, **{"p_" + field: max(row["p_" + short + "_regions"])}) for row in both]
        universities, y, p_chunk = _scorable(both, field, na_counts_as_no)
        universities, y, p_region = _scorable(highest, field, na_counts_as_no)
        line = {"field": field, "scored": len(y), "yes": int(y.sum()),
                "auroc_whole_chunk": auroc(y, p_chunk) if len(y) else None,
                "auroc_highest_region": auroc(y, p_region) if len(y) else None}

        judged = 0
        right = 0
        for row in both:
            gold_text = row.get("gold_" + short + "_text", "")
            if row.get("gold_" + field) != 1 or not gold_text or len(row["regions"]) < 2:
                continue
            if (capture(row["text"], gold_text) or 0) < 0.95:        # the copied text is not really in the file
                continue
            held = [capture(region, gold_text) or 0 for region in row["regions"]]
            if max(held) < 0.5:                                       # the copied text is spread over regions
                continue
            judged = judged + 1
            scores = row["p_" + short + "_regions"]
            if scores.index(max(scores)) == held.index(max(held)):
                right = right + 1
        line.update({"policies_with_2+_regions_judged": judged, "highest_region_is_the_coders": right})

        single = [abs(row["p_" + short + "_regions"][0] - row["p_" + field]) for row in both
                  if len(row["p_" + short + "_regions"]) == 1]
        line.update({"one_region_chunks": len(single),
                     "one_region_largest_difference": max(single) if single else None})
        lines.append(line)
    return pandas.DataFrame(lines).round(3)


# ============================================================ 4. speed

def timing(rows):
    """Seconds per syllabus for the two model steps, from the times saved with each answer."""
    lines = []
    for field, label in [("screen_ms", "2 Screen (whole syllabus)"), ("code_ms", "4 Code (chunk only)"),
                         ("regions_ms", "4b Regions (each region)")]:
        seconds = [row[field] / 1000 for row in rows if field in row]
        if seconds:
            lines.append({"step": label, "syllabi": len(seconds), "seconds_middle": numpy.median(seconds),
                          "seconds_average": numpy.mean(seconds), "minutes_all_together": sum(seconds) / 60})
    both = [(row["screen_ms"] + row.get("code_ms", 0) + row.get("regions_ms", 0)) / 1000 for row in rows if "screen_ms" in row]
    if both:
        lines.append({"step": "all model steps, per syllabus", "syllabi": len(both), "seconds_middle": numpy.median(both),
                      "seconds_average": numpy.mean(both), "minutes_all_together": sum(both) / 60})
    return pandas.DataFrame(lines).round(2)

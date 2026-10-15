# Step 5 · Rules: turns the probabilities into the codebook's answers, 1 / 0 / n/a, and fills the review queue.

from settings import CODE_FIELDS


def apply_rules(row, cutoffs):
    """One syllabus: the model's probabilities become 1 / 0 / n/a, plus the two policy-text fields."""
    result = {"id": row["id"], "review": ""}

    # 1. no policy: everything else is n/a
    if row["p_policy_found"] < cutoffs["policy_found"]:
        result["policy_found"] = 0
        for field in CODE_FIELDS:
            result[field] = "n/a"
        result["cs_language"] = "n/a"
        result["bp_language"] = "n/a"
        return result

    result["policy_found"] = 1

    # 2. the model sees a policy but no keyword located it: a person has to look
    if row.get("chunk", "") == "":
        for field in CODE_FIELDS:
            result[field] = ""
        result["cs_language"] = ""
        result["bp_language"] = ""
        result["review"] = "policy found, but no keyword matched"
        return result

    # 3. each field is 1 when its probability reaches its cutoff, otherwise 0
    for field in CODE_FIELDS:
        if row["p_" + field] >= cutoffs[field]:
            result[field] = 1
        else:
            result[field] = 0

    # 4. the policy text is the whole chunk, copied
    result["cs_language"] = row["chunk"] if result["cs_present"] == 1 else "n/a"
    result["bp_language"] = row["chunk"] if result["bp_present"] == 1 else "n/a"
    if result["cs_present"] == 0 and result["bp_present"] == 0:
        result["review"] = "policy found, but neither CS nor BP present"
    return result

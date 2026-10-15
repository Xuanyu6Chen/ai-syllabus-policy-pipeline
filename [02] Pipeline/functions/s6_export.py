# Step 6 · Export: one table per university, one row per syllabus, sorted so it can be split by subject.

import pandas

from settings import CODE_FIELDS

COLUMNS = (["id", "university", "file", "department", "term", "subject", "course", "section", "policy_found"] + CODE_FIELDS
           + ["cs_language", "bp_language", "review"])


def export(rows, university):
    """The export table of one university. rows: one per syllabus, with the fields of step 1 and step 5."""
    mine = [row for row in rows if row["university"] == university]
    if not mine:
        return pandas.DataFrame(columns=COLUMNS)
    table = pandas.DataFrame(mine)[COLUMNS]
    return table.sort_values(["subject", "course", "section", "file"]).reset_index(drop=True)

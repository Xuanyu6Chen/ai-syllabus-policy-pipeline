# Reads the hand-coded labels (the "gold") from each university's labelled/labels.csv, and matches them to syllabi by
# file name. Used by the Test section of the runner.

import csv
import re
from urllib.parse import unquote

from settings import DATA, LABELLED_FOLDER, UNIVERSITY_NAMES


def file_key(name):
    """A file name boiled down so the same syllabus matches everywhere:
    no extension, no leading "A_", lower case, letters and digits only."""
    name = unquote(str(name)).strip().strip('"')
    name = re.sub(r"\.(pdf|txt|docx?)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^A_", "", name)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def read_gold(universities, columns):
    """One dictionary per hand-coded syllabus: its university, its file key, each coded field as 1 / 0 / None,
    the policy text the coder copied, and its college and department.
    universities: short codes; a university with no labelled/labels.csv has no labels.
    columns: {our field name: its column in labels.csv}"""
    lines = []
    headers = []
    for university in universities:
        path = DATA / UNIVERSITY_NAMES[university] / LABELLED_FOLDER / "labels.csv"
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as file:
            table = csv.DictReader(file)
            headers = table.fieldnames
            lines = lines + list(table)
    gold = []
    not_coded = 0
    for line in lines:
        if line[_column(headers, "File Name")].strip() == "":
            continue
        raw = {}
        for field, header in columns.items():
            raw[field] = line[_column(headers, header)]
        if all(value.strip() == "" for value in raw.values()):      # a row somebody listed but never coded
            not_coded = not_coded + 1
            continue
        label = {"university": line["university"], "key": file_key(line[_column(headers, "File Name")])}
        for field in raw:
            label[field] = _code(raw[field])
        label["cs_language"] = _text(line[_column(headers, "CS Lang.")])
        label["bp_language"] = _text(line[_column(headers, "BP Lang.")])
        label["college"] = _text(line[_column(headers, "College")])
        label["department"] = _text(line[_column(headers, "Department")])
        gold.append(label)
    print(len(gold), "hand-coded syllabi read from labels.csv,", not_coded, "listed but not coded")
    return gold


def gold_policy_found(label):
    """Does a hand-coded syllabus count as "has a policy"? Here: when CS or BP is coded 1.
    A syllabus can be coded on the other fields but has CS = 0 and BP = 0, and this rule then says no policy."""
    if label["cs_present"] == 1 or label["bp_present"] == 1:
        return 1
    return 0


def attach(rows, gold):
    """Add the hand-coded answers to the syllabi they belong to, as gold_<field>,
    plus gold_text: the policy text the coder copied (gold_cs_text and gold_bp_text: its CS and BP parts)."""
    by_key = {}
    for label in gold:
        by_key[(label["university"], label["key"])] = label
    matched = 0
    for row in rows:
        label = by_key.get((row["university"], file_key(row["file"])))
        if label is None:
            continue
        matched = matched + 1
        for field, value in label.items():
            if field not in ("university", "key", "cs_language", "bp_language"):
                row["gold_" + field] = value
        row["gold_text"] = (label["cs_language"] + " " + label["bp_language"]).strip()
        row["gold_cs_text"] = label["cs_language"]
        row["gold_bp_text"] = label["bp_language"]
    print(matched, "of", len(rows), "syllabi have hand-coded labels")
    return rows


def _column(headers, wanted):
    """The name of a column: an exact header match first, otherwise a header that starts with the wanted text."""
    wanted = wanted.strip()
    if wanted in headers:
        return wanted
    for header in headers:
        if header.startswith(wanted):
            return header
    raise KeyError("No column '" + wanted + "' in labels.csv. Headers are: " + ", ".join(h for h in headers if h))


def _code(cell):
    """A labels.csv value as 1, 0 or None. Anything that is not a clear 1 or 0 (n/a, empty, a typo) is None."""
    text = str(cell).strip() if cell is not None else ""
    if text in ("1", "1.0"):
        return 1
    if text in ("0", "0.0"):
        return 0
    return None


def _text(cell):
    """A labels.csv value as text; n/a and empty become ""."""
    text = str(cell).strip() if cell is not None else ""
    return "" if text.lower() == "n/a" else text

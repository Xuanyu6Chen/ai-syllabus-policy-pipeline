# Step 1 · Input: a university's syllabi become one jsonl in [01] Data (syllabi.jsonl, or labelled/labelled.jsonl for the
# hand-coded set), one row per syllabus: the parts of the file name and the text with emails and phone numbers replaced.
# A PDF or Word file that has no text file yet is converted first, and its text is kept in txt/ so it is converted only
# once. helpers.build_input rebuilds a jsonl only when its text files or this code changed; tests read it directly.

import csv
import hashlib
import io
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

import helpers
from labels import file_key, gold_policy_found, read_gold
from settings import (CONVERTIBLE, DATA, GOLD_COLUMNS, LABELLED_FOLDER, MIN_TEXT_CHARS, NAME_PATTERNS, SCRUB, TERM,
                      UNIVERSITY_NAMES)

logging.getLogger("pdfminer").setLevel(logging.ERROR)     # its font warnings do not change the text it gives


# ============================================================ text from PDF and Word files

def real_format(data, suffix):
    """What a file really is, read from its first bytes: some files are named .docx but are a PDF, an old .doc or a
    saved web page. Anything else keeps the format its name says."""
    if data[:5] == b"%PDF-":
        return ".pdf"
    if data[:2] == b"PK":
        return ".docx"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc"
    if b"<html" in data[:2048].lower() or data[:2048].lstrip().lower().startswith(b"<!doctype html"):
        return ".html"
    return suffix


def file_text(data, suffix):
    """The text of one PDF or Word file, the way the project's original text files were made.
    Gives back (its text, a problem); the problem is "" when the text can be used."""
    suffix = real_format(data, suffix)
    try:
        if suffix == ".pdf":
            import pdfplumber                               # only needed when something has to be converted
            text = ""
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"          # each page followed by a blank line
        elif suffix == ".docx":
            import docx
            text = ""
            for paragraph in docx.Document(io.BytesIO(data)).paragraphs:
                text += paragraph.text + "\n"
        elif suffix in (".doc", ".html"):
            if shutil.which("textutil") is None:
                return "", "a " + suffix + " file can only be converted on the Mac (macOS textutil)"
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / ("file" + suffix)
                source.write_bytes(data)
                done = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(source)], capture_output=True)
                if done.returncode != 0:
                    return "", "could not be read: " + done.stderr.decode(errors="replace")[:200]
                text = done.stdout.decode("utf-8", errors="replace")
        else:
            return "", "not a PDF or Word file"
    except Exception as problem:            # a damaged or locked file: it is named in the problem, and the others go on
        return "", "could not be read: " + str(problem)[:200]
    if len(text.strip()) < MIN_TEXT_CHARS:
        return "", "only " + str(len(text.strip())) + " characters of text (a scan? OCR is not set up)"
    return text, ""


def convert_missing(university):
    """Give every PDF or Word file in <University>/pdf.zip that has no text file yet its text file in <University>/txt/
    (a department subfolder is kept). Files that give no text are listed in <University>/no text.csv."""
    folder = university_folder(university)
    if not (folder / "pdf.zip").exists():
        print(university + ": no pdf.zip, nothing to convert")
        return
    have = set(path.stem for path in (folder / "txt").rglob("*.txt"))
    converted = 0
    problems = []
    with zipfile.ZipFile(folder / "pdf.zip") as archive:
        for member in sorted(archive.namelist()):
            path = Path(member)
            if member.endswith("/") or path.stem in have:
                continue
            if path.suffix.lower() not in CONVERTIBLE:
                problems.append({"file": member, "problem": "not a PDF or Word file"})
                continue
            text, problem = file_text(archive.read(member), path.suffix.lower())
            if problem:
                problems.append({"file": member, "problem": problem})
                continue
            target = folder / "txt" / path.with_suffix(".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            have.add(path.stem)
            converted = converted + 1
    if problems or (folder / "no text.csv").exists():      # rewritten every time, so it never lists a file that now has text
        with open(folder / "no text.csv", "w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=["file", "problem"])
            writer.writeheader()
            writer.writerows(problems)
    print(university + ":", converted, "converted to text,", len(problems), "without text" +
          (" (listed in no text.csv)" if problems else ""))


# ============================================================ which syllabi, and what their file names say

def parse_name(university, file_name):
    """Subject, course and section, read out of a file name with its university's pattern. A name that does not fit
    gives blanks."""
    name = unquote(file_name)
    name = re.sub(r"\.(txt|pdf|docx?)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^A_", "", name)
    found = {"subject": "", "course": "", "section": ""}
    match = re.search(NAME_PATTERNS[university], name) if university in NAME_PATTERNS else None
    if match:
        for part, value in match.groupdict().items():
            found[part] = value or ""
    return found


def write_syllabi_csv(university):
    """<University>/syllabi.csv: one row per text file, with its department (its subfolder, where there is one), term,
    subject, course and section."""
    folder = university_folder(university) / "txt"
    rows = []
    for path in sorted(folder.rglob("*.txt")):
        row = {"file": str(path.relative_to(folder)), "department": _department(path, folder), "term": TERM}
        row.update(parse_name(university, path.name))
        rows.append(row)
    with open(university_folder(university) / "syllabi.csv", "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["file", "department", "term", "subject", "course", "section"])
        writer.writeheader()
        writer.writerows(rows)
    unparsed = sum(1 for row in rows if row["subject"] == "")
    print(university + ": syllabi.csv,", len(rows), "files,", unparsed, "whose name does not fit the pattern")


def list_files(universities, labelled_only):
    """Every syllabus of a test, in a fixed order: by university as listed, then by file name.
    labelled_only: True = only the hand-coded syllabi, in <University>/labelled/txt/; False = every text file in
    <University>/txt/."""
    sources = []
    for university in universities:
        if labelled_only:
            folder = university_folder(university) / LABELLED_FOLDER / "txt"
        else:
            folder = university_folder(university) / "txt"
        found = []
        for path in folder.rglob("*.txt"):
            found.append({"university": university, "file": path.name, "department": _department(path, folder),
                          "where": str(path.relative_to(DATA)), "size": path.stat().st_size})
        if not found:
            raise FileNotFoundError("No syllabi for " + university + " in " + str(folder))
        sources = sources + sorted(found, key=lambda source: source["where"])
    return sources


def load_syllabus(source):
    """One syllabus becomes one row: where it came from, the parts of its file name, and its text with emails and
    phone numbers replaced."""
    text = helpers.scrub(read_text(source["where"]), SCRUB)
    row = {"university": source["university"], "file": source["file"], "department": source["department"], "term": TERM}
    row.update(parse_name(source["university"], source["file"]))
    row["n_chars"] = len(text)
    row["text"] = text
    return row


def jsonl_path(university, labelled):
    """Where a university's step-1 jsonl lives: <University>/syllabi.jsonl, or <University>/labelled/labelled.jsonl."""
    if labelled:
        return university_folder(university) / LABELLED_FOLDER / "labelled.jsonl"
    return university_folder(university) / "syllabi.jsonl"


def add_labels(university, rows):
    """For labelled.jsonl: each row gets its hand-coded answers from labels.csv as `labels` (None when it has none):
    the coded fields, policy_found, the CS / BP text the coder copied, and the coder's college and department."""
    by_key = {}
    for label in read_gold([university], GOLD_COLUMNS):
        by_key[label["key"]] = label
    for row in rows:
        label = by_key.get(file_key(row["file"]))
        if label is None:
            row["labels"] = None
            continue
        row["labels"] = {"policy_found": gold_policy_found(label)}
        for field, value in label.items():
            if field not in ("university", "key"):
                row["labels"][field] = value
    return rows


def labels_stamp(university):
    """A short code for a university's labels.csv: it changes whenever the file does."""
    path = university_folder(university) / LABELLED_FOLDER / "labels.csv"
    if not path.exists():
        return None
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def read_text(where):
    """The text of a syllabus file, given as a path inside [01] Data."""
    return (DATA / where).read_text(encoding="utf-8", errors="replace")


def university_folder(university):
    """A university's folder in [01] Data, named by its full name."""
    if university not in UNIVERSITY_NAMES:
        raise KeyError("Unknown university '" + university + "'. The short codes are: " + ", ".join(UNIVERSITY_NAMES))
    return DATA / UNIVERSITY_NAMES[university]


def _department(path, folder):
    """A file in a subfolder of txt/ takes the subfolder's name as its department."""
    return path.parent.name if path.parent != folder else ""

# Checks every step on small made-up data, on the Mac: no Kev, no real syllabi, nothing written outside a temporary
# folder. A stand-in Kev server on this Mac answers the Kev questions. Run it after every change:
#   python "[02] Pipeline/runners/checks.py"     (from the project folder, with the packages in requirements.txt)

import csv
import http.server
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "functions"))

import helpers
import labels
import metrics
import s1_input
import s2_screen_kev
import s3_chunk
import s4_code_kev
import s4b_regions_kev
import s5_rules
import s6_export
import server_kev
import settings
import show

FAILED = []

# Made-up universities for the checks, next to the placeholder in settings.py
settings.UNIVERSITY_NAMES.update({"UNIB": "University B", "UNIC": "University C", "UNID": "University D"})


def fake_input(rows):
    """A made-up step 1 for the checks: the rows as one jsonl in a made-up [01] Data, and the test pointed at it."""
    path = helpers.DATA / "made-up.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    helpers._write_record(helpers.INPUT, {"step": helpers.INPUT, "files": ["made-up.jsonl"], "rows": len(rows),
                                          "version": helpers._version({}, {}, rows)})


def check(what, result):
    """One check: print it, and remember it when it fails."""
    print("  ", "ok  " if result else "FAIL", what)
    if not result:
        FAILED.append(what)


# ============================================================ step 1 · Input

def made_up_pdf(text):
    """The bytes of a one-page PDF with this text on it (no text at all when text is "")."""
    import fitz                                            # PyMuPDF, only used here to make the made-up PDFs
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    return document.tobytes()


def made_up_docx(lines):
    import docx
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    data = io.BytesIO()
    document.save(data)
    return data.getvalue()


def check_names():
    print("Step 1 · file names")
    check("a name gives subject, course and section",
          s1_input.parse_name("UNI", "Fall-2025-ACG-2021-RVC-.txt") == {"subject": "ACG", "course": "2021", "section": "RVC"})
    check("a leading A_ is dropped and the name is URL-decoded",
          s1_input.parse_name("UNI", "A_Fall-2025-NGR-6244L-104%2D.txt") == {"subject": "NGR", "course": "6244L", "section": "104"})
    check("a university with no pattern gives blanks", s1_input.parse_name("UNIB", "H456_Health_Policy.txt")["course"] == "")
    check("a name that fits no pattern gives blanks, not an error",
          s1_input.parse_name("UNI", "Fall-2025-SANDBOX-7000-PhD-Dissertation-Sample-1-.txt") == {"subject": "", "course": "", "section": ""})


def check_s1(folder):
    print("Step 1 · Input (a made-up [01] Data)")
    data = folder / "Data"
    s1_input.DATA = data                                   # the step reads this made-up Data instead of the real one
    uni = data / settings.UNIVERSITY_NAMES["UNI"]          # folders go by full name

    txt = uni / "txt"
    txt.mkdir(parents=True)
    (txt / "Fall-2025-ACG-2021-RVC-.txt").write_text(
        "Instructor: jane.doe@uni.edu, office 555-555-0100.\nUse of AI is allowed.", encoding="utf-8")
    with zipfile.ZipFile(uni / "pdf.zip", "w") as archive:
        archive.writestr("Fall-2025-ACG-2021-RVC-.pdf", made_up_pdf("already has a text file"))
        archive.writestr("Fall-2025-ENC-1101-U01-.pdf", made_up_pdf("Use of AI tools is not allowed in this course."))
        archive.writestr("Fall-2025-ENC-1101-U02-.docx", made_up_docx(["AI policy", "Cite any AI use."]))
        archive.writestr("Fall-2025-ENC-1101-U03-.pdf", made_up_pdf(""))
        archive.writestr("Fall-2025-ENC-1101-U04-.pdf", b"this is not a PDF")
        archive.writestr("Fall-2025-ENC-1101-U06-.docx", made_up_pdf("Really a PDF. Copilot is allowed."))
        archive.writestr("slides.pptx", b"not a syllabus")
        if shutil.which("textutil"):
            source = folder / "made-up.txt"
            source.write_text("A .doc syllabus. ChatGPT may be used.", encoding="utf-8")
            subprocess.run(["textutil", "-convert", "doc", str(source), "-output", str(folder / "made-up.doc")], check=True)
            archive.write(folder / "made-up.doc", "Fall-2025-ENC-1101-U05-.doc")

    s1_input.convert_missing("UNI")
    made = sorted(path.name for path in txt.glob("*.txt"))
    check("a PDF with text becomes a text file", "Fall-2025-ENC-1101-U01-.txt" in made)
    check("its text has the original text files' shape: the page followed by a blank line",
          (txt / "Fall-2025-ENC-1101-U01-.txt").read_text(encoding="utf-8") == "Use of AI tools is not allowed in this course.\n\n")
    check("a .docx becomes one line per paragraph, as the original text files were made",
          (txt / "Fall-2025-ENC-1101-U02-.txt").read_text(encoding="utf-8") == "AI policy\nCite any AI use.\n")
    if shutil.which("textutil"):
        check("a .doc is converted on the Mac", "ChatGPT may be used" in (txt / "Fall-2025-ENC-1101-U05-.txt").read_text(encoding="utf-8"))
    check("a file named .docx that is really a PDF is read as a PDF",
          "Copilot is allowed" in (txt / "Fall-2025-ENC-1101-U06-.txt").read_text(encoding="utf-8"))
    check("a saved web page is recognized from its content", s1_input.real_format(b"\r\n<!DOCTYPE html><html>", ".docx") == ".html")
    check("a file that already has a text file is left alone",
          "Use of AI is allowed." in (txt / "Fall-2025-ACG-2021-RVC-.txt").read_text(encoding="utf-8"))
    with open(uni / "no text.csv", newline="", encoding="utf-8") as file:
        problems = {line["file"]: line["problem"] for line in csv.DictReader(file)}
    check("a PDF with no text, a broken PDF and a .pptx are listed in no text.csv, not converted",
          sorted(problems) == ["Fall-2025-ENC-1101-U03-.pdf", "Fall-2025-ENC-1101-U04-.pdf", "slides.pptx"])
    before = sorted(path.stat().st_mtime for path in txt.glob("*.txt"))
    s1_input.convert_missing("UNI")
    check("converting again changes nothing", sorted(path.stat().st_mtime for path in txt.glob("*.txt")) == before)

    s1_input.write_syllabi_csv("UNI")
    with open(uni / "syllabi.csv", newline="", encoding="utf-8") as file:
        listed = list(csv.DictReader(file))
    check("syllabi.csv lists every text file with its name parts",
          len(listed) == len(made) and listed[0]["subject"] == "ACG" and listed[0]["term"] == settings.TERM)

    sources = s1_input.list_files(["UNI"], False)
    check("list_files gives every text file, in name order", [source["file"] for source in sources] == made)
    row = s1_input.load_syllabus(sources[0])
    check("emails and phone numbers are replaced",
          "jane.doe" not in row["text"] and "555-0100" not in row["text"] and "[email]" in row["text"] and "[phone]" in row["text"])
    check("the row keeps university, file, name parts and length",
          row["university"] == "UNI" and row["subject"] == "ACG" and row["n_chars"] == len(row["text"]))

    unib = data / settings.UNIVERSITY_NAMES["UNIB"]
    (unib / "txt" / "Healthcare").mkdir(parents=True)
    (unib / "txt" / "Healthcare" / "H456_Health_Policy.txt").write_text("Health policy.", encoding="utf-8")
    check("a file in a subfolder takes it as its department", s1_input.list_files(["UNIB"], False)[0]["department"] == "Healthcare")

    (uni / settings.LABELLED_FOLDER / "txt").mkdir(parents=True)
    (uni / settings.LABELLED_FOLDER / "txt" / "Fall-2025-ENC-1101-U01-.txt").write_bytes(b"Line one.\r\nUse of AI is allowed.\r\n")
    unic = data / settings.UNIVERSITY_NAMES["UNIC"] / settings.LABELLED_FOLDER / "txt"
    unic.mkdir(parents=True)
    (unic / "Fall-2025-HUM-2020-0W66-.txt").write_text("Another university.", encoding="utf-8")
    sources = s1_input.list_files(["UNI"], True)
    check("labelled only: the files come from <University>/labelled/txt, for that university only",
          [source["file"] for source in sources] == ["Fall-2025-ENC-1101-U01-.txt"])
    check("a text file with Windows line endings reads the same as one with Mac line endings",
          s1_input.load_syllabus(sources[0])["text"] == "Line one.\nUse of AI is allowed.\n")
    try:
        s1_input.list_files(["UNID"], True)
        check("a university with no syllabi stops with a clear error", False)
    except FileNotFoundError:
        check("a university with no syllabi stops with a clear error", True)

    labels.DATA = data                                     # labels.csv is read from the made-up Data too
    helpers.start(folder / "Output input", data)
    choice = {"UNIVERSITIES": ["UNI"], "LABELLED_ONLY": False}
    report = helpers.build_input(s1_input, choice)
    rows = helpers.read("1 input")
    check("step 1 gives ids like UNI-0001 in name order", [row["id"] for row in rows][:2] == ["UNI-0001", "UNI-0002"])
    check("its jsonl is in [01] Data/<University>/syllabi.jsonl, with no copy in Output",
          (uni / "syllabi.jsonl").exists() and (uni / "syllabi record.json").exists()
          and not (folder / "Output input" / "1 input.jsonl").exists() and report["universities"][0]["state"] == "built")
    record = helpers.read_record("1 input")
    check("the test's record notes which syllabi it chose and which jsonl it read",
          record["settings"]["UNIVERSITIES"] == ["UNI"] and record["files"] == [str((uni / "syllabi.jsonl").relative_to(data))])
    stamp = (uni / "syllabi.jsonl").stat().st_mtime_ns
    version = record["version"]
    report = helpers.build_input(s1_input, choice)
    check("a second run only checks the jsonl: not rebuilt, same version",
          report["state"] == "current" and (uni / "syllabi.jsonl").stat().st_mtime_ns == stamp
          and helpers.read_record("1 input")["version"] == version)
    (txt / "Fall-2025-ENC-1101-U07-.txt").write_text("A new syllabus. ChatGPT is not allowed.", encoding="utf-8")
    report = helpers.build_input(s1_input, choice)
    check("a new text file rebuilds the jsonl, says why, and gives a new version",
          report["universities"][0]["state"] == "built" and "the text files in txt/" in report["universities"][0]["changed"]
          and len(helpers.read("1 input")) == len(made) + 1 and helpers.read_record("1 input")["version"] != version)
    helpers.build_input(s1_input, dict(choice, UNIVERSITIES=["UNI", "UNIB"]))
    check("a test of two universities reads both jsonl files",
          sorted(set(row["university"] for row in helpers.read("1 input"))) == ["UNI", "UNIB"]
          and (unib / "syllabi.jsonl").exists())

    labelled = dict(choice, LABELLED_ONLY=True)
    report = helpers.build_input(s1_input, labelled)
    check("choosing other syllabi points the test at other files", len(helpers.read("1 input")) == 1
          and (uni / settings.LABELLED_FOLDER / "labelled.jsonl").exists())
    check("a university with no labels.csv: each row's labels are None", helpers.read("1 input")[0]["labels"] is None)
    with open(uni / settings.LABELLED_FOLDER / "labels.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["university", "College", "Department", "File Name", "Prohibited", '"Ask Instructor"', "CR", "BP",
                         "CS", "Specific Context", "BP Lang.", "CS Lang."])
        writer.writerow(["UNI", "Arts", "English", "Fall-2025-ENC-1101-U01-.pdf", "0", "0", "0", "0", "1", "1", "", "AI is allowed."])
    version = helpers.read_record("1 input")["version"]
    report = helpers.build_input(s1_input, labelled)
    row = helpers.read("1 input")[0]
    check("a new labels.csv rebuilds labelled.jsonl with each row's labels",
          report["universities"][0]["state"] == "built" and row["labels"]["cs_present"] == 1
          and row["labels"]["policy_found"] == 1 and row["labels"]["college"] == "Arts")
    check("but the text did not change, so the version stays and later steps do not rerun",
          helpers.read_record("1 input")["version"] == version)

    s1_input.DATA = settings.DATA                          # back to the real paths
    labels.DATA = settings.DATA


# ============================================================ step 3 · Chunk

EXAMPLE = """Course Policies
Attendance is required in every class meeting.
Late work loses ten points for each day it is late.
Exams are closed book.
Bring a calculator to every exam.
Office hours are on Tuesdays.
Email me if you cannot attend.
Use of Artificial Intelligence
You may use ChatGPT to brainstorm ideas for your essays.
You may not use it to write your answers.
If you use an AI tool, say so at the end of your paper.
Grading
Homework is worth 30 percent of the grade.
The midterm is worth 30 percent.
The final exam is worth 40 percent.
Grades are posted on Canvas.
Regrade requests are due within one week.
Textbook
The textbook is required.
Older editions are fine.
The library has copies on reserve."""


def check_s3():
    print("Step 3 · Chunk (WINDOW = " + str(settings.WINDOW) + ")")
    chunk = s3_chunk.find_chunk(EXAMPLE)
    check("the made-up syllabus's chunk starts at 'Late work'", chunk.startswith("Late work"))
    check("and ends at 'Grades are posted on Canvas.'", chunk.endswith("Grades are posted on Canvas."))
    check("'LLM' does not match inside 'enrollment'", "LLM" not in s3_chunk.keywords_in("Late enrollment is not allowed."))
    check("'AI' must be in capitals ('said' and 'Ai' do not match)", s3_chunk.keywords_in("She said Ai was fine.") == [])
    check("a plural keyword matches ('LLMs')", "LLM" in s3_chunk.keywords_in("LLMs may not be used."))
    check("has_keyword agrees with keywords_in (capitals, any case, whole words, plurals)",
          [s3_chunk.has_keyword(text) for text in ["She said Ai was fine.", "chatgpts are banned", "Late enrollment.", "AIs help"]]
          == [False, True, False, True])
    check("a syllabus with no keyword gives an empty chunk", s3_chunk.find_chunk("Exams are closed book. Bring a pencil.") == "")
    two_regions = s3_chunk.find_chunk("Use of AI is allowed.\n\n" + "Filler sentence here.\n\n" * 20 + "ChatGPT must be cited.")
    check("two policy regions far apart are joined with the break", two_regions.count(settings.BREAK.strip()) == 1)


# ============================================================ steps 2 and 4 · Kev (a stand-in server)

class StandInKev(http.server.BaseHTTPRequestHandler):
    """Answers like Kev: 0.9 for every question, or an error when the text says FAIL."""
    def do_GET(self):                                       # server_kev.is_up() asks for /v1/models
        self._send(200, {"data": []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "FAIL" in body["state"]:
            self._send(500, {"error": "made-up failure"})
            return
        answers = {name: {"noul": 0.9} for name in body["questions"]}
        self._send(200, {"answers": answers})

    def _send(self, status, content):
        data = json.dumps(content).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *arguments):                      # keep the check's output quiet
        pass


def check_kev(folder):
    import contextlib
    print("Steps 2 and 4 · Kev (a stand-in server on this Mac)")
    server = http.server.HTTPServer(("127.0.0.1", 0), StandInKev)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server_kev._url = "http://127.0.0.1:" + str(server.server_port) + "/v1/systemone"
    server_kev._details = {"model": "made-up model"}
    try:
        check("is_up() sees the server", server_kev.is_up())
        answer = s2_screen_kev.screen_syllabus({"text": "Use of AI is allowed."})
        check("screen_syllabus gives p_policy_found", answer == {"p_policy_found": 0.9})
        answer = s4_code_kev.code_syllabus({"chunk": "Use of AI is allowed."})
        check("code_syllabus gives one probability per field", sorted(answer) == sorted("p_" + f for f in settings.CODE_FIELDS))
        check("only syllabi with a chunk are coded", s4_code_kev.needs_coding({"chunk": "x"}) and not s4_code_kev.needs_coding({"chunk": ""}))

        # a model step through helpers.run_step: errors are noted, never saved as answers, and retried on the next run
        helpers.start(folder / "Output kev", folder / "Data kev")
        rows = [{"id": "T-0001", "text": "Use of AI is allowed."}, {"id": "T-0002", "text": "FAIL here"},
                {"id": "T-0003", "text": "No policy."}]
        fake_input(rows)
        report = helpers.run_step("2 screen", s2_screen_kev.screen_syllabus, reads="1 input", server=server_kev, model="model A")
        saved = helpers.read("2 screen")
        check("the step's report says 2 of 3 done, 1 error", report["state"] == "done" and report["done"] == 2
              and report["total"] == 3 and list(report["errors"]) == ["T-0002"])
        record = helpers.read_record("2 screen")
        check("a failed Kev call is not saved as an answer", [row["id"] for row in saved] == ["T-0001", "T-0003"])
        check("and it is noted in the record", list(record["errors"]) == ["T-0002"])
        check("the record notes the model", record["settings"].get("MODEL") == "model A" and record["model_server"]["model"] == "made-up model")
        helpers.run_step("2 screen", s2_screen_kev.screen_syllabus, reads="1 input", server=server_kev, model="model B")
        check("another model makes the step start over, with the old answers set aside",
              (folder / "Output kev" / "old 2 screen.jsonl").exists() and helpers.read_record("2 screen")["settings"]["MODEL"] == "model B")

        # step 4b: CS and BP for each region of a chunk
        chunk = "Use of AI is allowed." + settings.BREAK + "Cite ChatGPT." + settings.BREAK + "AI Ethics week."
        check("a chunk splits into its regions at the break", s4b_regions_kev.regions_of(chunk) == ["Use of AI is allowed.", "Cite ChatGPT.", "AI Ethics week."])
        answer = s4b_regions_kev.code_regions({"chunk": chunk})
        check("4b gives one CS and one BP probability per region",
              answer["p_cs_regions"] == [0.9, 0.9, 0.9] and answer["p_bp_regions"] == [0.9, 0.9, 0.9] and len(answer["regions"]) == 3)
        helpers.write("3 chunks", [{"id": "T-0001", "chunk": chunk}, {"id": "T-0002", "chunk": "AI ok." + settings.BREAK + "FAIL here"},
                                   {"id": "T-0003", "chunk": "One region about AI."}, {"id": "T-0004", "chunk": ""}])
        report = helpers.run_step("4b regions", s4b_regions_kev.code_regions, reads="3 chunks",
                                  only=s4b_regions_kev.needs_regions, server=server_kev, model="model B")
        saved = {row["id"]: row for row in helpers.read("4b regions")}
        check("4b: a syllabus with one failed region is not saved, and is noted as an error",
              sorted(saved) == ["T-0001", "T-0003"] and list(report["errors"]) == ["T-0002"])
        check("4b: a 1-region chunk is asked once, and a syllabus with no chunk is skipped",
              saved["T-0003"]["p_cs_regions"] == [0.9] and report["total"] == 3)
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            show.regions_summary("4b regions")
        check("4b's summary counts regions and the syllabi with a region at 0.5 or more", "regions_0.5_or_more" in text.getvalue())
    finally:
        server.shutdown()
        server_kev._url = None
        server_kev._details = {}
    report = helpers.run_step("2 screen", s2_screen_kev.screen_syllabus, reads="1 input", server=server_kev, model="model B")
    check("without a running server the step waits instead of failing", len(helpers.read("2 screen")) == 2
          and report["state"] == "waiting" and "GPU" in report["why"])


# ============================================================ step 5 · Rules

def check_s5():
    print("Step 5 · Rules")
    cutoffs = {"policy_found": 0.5}
    for field in settings.CODE_FIELDS:
        cutoffs[field] = 0.5
    row = {"id": "E-1", "chunk": "You may use ChatGPT to brainstorm.", "p_policy_found": 0.93, "p_cs_present": 0.90,
           "p_bp_present": 0.10, "p_prohibited": 0.20, "p_specific_context": 0.80, "p_ask_instructor": 0.05,
           "p_citation_required": 0.30}
    result = s5_rules.apply_rules(row, cutoffs)
    check("a policy: each field is 1 or 0 by its cutoff", result["cs_present"] == 1 and result["bp_present"] == 0 and result["specific_context"] == 1)
    check("CS language is the whole chunk, BP language is n/a", result["cs_language"] == row["chunk"] and result["bp_language"] == "n/a")
    result = s5_rules.apply_rules(dict(row, p_policy_found=0.2), cutoffs)
    check("no policy: every field is n/a", result["policy_found"] == 0 and all(result[f] == "n/a" for f in settings.CODE_FIELDS))
    result = s5_rules.apply_rules(dict(row, chunk=""), cutoffs)
    check("a policy but no chunk: sent to review", result["review"] == "policy found, but no keyword matched")
    result = s5_rules.apply_rules(dict(row, p_cs_present=0.1), cutoffs)
    check("a policy but neither CS nor BP: sent to review", result["review"] == "policy found, but neither CS nor BP present")


# ============================================================ step 6 · Export

def check_s6():
    print("Step 6 · Export")
    cutoffs = {field: 0.5 for field in ["policy_found"] + settings.CODE_FIELDS}
    rows = []
    for number, p, course in [(1, 0.9, "4101"), (2, 0.1, "2021")]:
        row = {"id": "UNI-000" + str(number), "university": "UNI", "file": "f" + str(number) + ".txt", "department": "",
               "term": settings.TERM, "subject": "ACG", "course": course, "section": "U0" + str(number),
               "chunk": "Use of AI is allowed.", "p_policy_found": p}
        for field in settings.CODE_FIELDS:
            row["p_" + field] = p
        row.update(s5_rules.apply_rules(row, cutoffs))
        rows.append(row)
    table = s6_export.export(rows, "UNI")
    check("the export has one row per syllabus, sorted by subject and course", list(table["id"]) == ["UNI-0002", "UNI-0001"])
    check("with the codebook's answers", list(table["policy_found"]) == [0, 1] and list(table["cs_present"]) == ["n/a", 1])
    check("and the same columns every time", list(table.columns) == s6_export.COLUMNS)
    empty = s6_export.export(rows, "UNIC")
    check("another university gives an empty export with the same columns", len(empty) == 0 and list(empty.columns) == s6_export.COLUMNS)


# ============================================================ helpers · resume and change detection

STAND_IN_SETTING = 1


def stand_in_step(row):
    """A made-up step that reads an ALL-CAPS setting, so a change to the setting must make the step run again."""
    return {"doubled": row["number"] * 2 * STAND_IN_SETTING}


def check_helpers(folder):
    global STAND_IN_SETTING
    print("helpers · resume and change detection")
    helpers.start(folder / "Output helpers", folder / "Data helpers")
    fake_input([{"id": "T-000" + str(n), "number": n} for n in range(1, 4)])
    counted = []

    class Bar:                                             # a stand-in progress bar that counts its updates
        def update(self, n):
            counted.append(n)

        def close(self):
            pass
    report = helpers.run_step("3 chunks", stand_in_step, reads="1 input", progress=lambda total, name: Bar())
    check("a step runs on every syllabus", [row["doubled"] for row in helpers.read("3 chunks")] == [2, 4, 6])
    check("the progress bar moves once per syllabus", counted == [1, 1, 1])
    check("a finished step reports itself current next time",
          helpers.run_step("3 chunks", stand_in_step, reads="1 input")["state"] == "current")
    with open(helpers.file_of("3 chunks"), "w", encoding="utf-8") as file:     # pretend the run was cut off
        file.write(json.dumps({"id": "T-0001", "doubled": 2}) + "\n" + '{"id": "T-00')
    helpers.run_step("3 chunks", stand_in_step, reads="1 input")
    check("a run that was cut off continues where it stopped", sorted(row["id"] for row in helpers.read("3 chunks")) == ["T-0001", "T-0002", "T-0003"])
    STAND_IN_SETTING = 10
    check("a changed setting is noticed", "setting STAND_IN_SETTING" in helpers._problem("3 chunks"))
    report = helpers.run_step("3 chunks", stand_in_step, reads="1 input")
    check("and the step runs again with it, every syllabus counted as new", [row["doubled"] for row in helpers.read("3 chunks")] == [20, 40, 60]
          and report["new"] == 3 and report["changed"] == ["setting STAND_IN_SETTING"])
    STAND_IN_SETTING = 1
    check("a step whose input is missing waits and says for what",
          helpers.run_step("4 code", stand_in_step, reads="9 missing")["why"] == "'9 missing' not made yet")
    tried = helpers.try_first(lambda row: 1 / 0 if row["number"] == 2 else "ok", helpers.read("1 input"), "number")
    check("try_first shows an error and goes on", [line["answer"][:5] for line in tried] == ["ok", "ERROR", "ok"])
    helpers.run_step("3 chunks", stand_in_step, reads="1 input")          # made again with the setting back at 1
    board = helpers.status("3 chunks")
    check("the status of a made step: ready, its rows and when", board["state"] == "ready" and board["rows"] == 3 and board["made"])
    check("the status of a step not made yet", helpers.status("5 decisions")["state"] == "not made yet")
    import pandas
    helpers.save_output("scores by field", pandas.DataFrame([{"field": "cs_present"}]), settings.TEST_RESULTS)
    check("a Test table is saved in Output/test_results/", (helpers.OUTPUT / "test_results" / "scores by field.csv").exists()
          and not (helpers.OUTPUT / "scores by field.csv").exists())


# ============================================================ show · what the runner displays

def check_show(folder):
    print("show · what the runner displays (on made-up step files)")
    import contextlib
    helpers.start(folder / "Output show", folder / "Data show")
    fake_input([{"id": "T-0001", "university": "UNI", "subject": "ACG", "n_chars": 100},
                              {"id": "T-0002", "university": "UNI", "subject": "", "n_chars": 300}])
    helpers.write("2 screen", [{"id": "T-0001", "p_policy_found": 0.9, "screen_ms": 500.0},
                               {"id": "T-0002", "p_policy_found": 0.1, "screen_ms": 700.0}])
    helpers.write("3 chunks", [{"id": "T-0001", "chunk": "AI is allowed." + settings.BREAK + "Cite ChatGPT.", "chunk_chars": 40,
                                "keywords": ["AI", "ChatGPT"]}, {"id": "T-0002", "chunk": "", "chunk_chars": 0, "keywords": []}])
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        show.header(2, "model A")
        show.report({"step": "2 screen", "state": "done", "done": 2, "total": 2, "new": 2, "seconds": 1.2, "errors": {}})
        show.report({"step": "4 code", "state": "waiting", "done": 0, "total": 1, "why": "the model needs a GPU runtime"})
        show.input_summary(helpers.read("1 input"), ["UNI"])
        show.probabilities("2 screen")
        show.chunks_summary(helpers.read("3 chunks"))
        show.status_board(False, False, ["UNI"])
    shown = text.getvalue()
    check("the header names the step, what it reads (with its count) and the model",
          "Step 2 · Screen (Kev)" in shown and "1 input (2 syllabi)" in shown and "model A" in shown)
    check("a finished step's line: done, errors, time per syllabus", "✓ 2 of 2 done · 0 errors · 1.2 s (0.6 s per syllabus)" in shown)
    check("a waiting step's line says why", "⏸ 0 of 1 done · the model needs a GPU runtime" in shown)
    check("the chunk table counts separate regions", "2_regions" in shown)
    check("the status board marks steps 4 and 5 as waiting, and why",
          "waiting: needs a GPU" in shown and "waiting: CUTOFFS empty" in shown)
    with contextlib.redirect_stderr(io.StringIO()):
        progress = show.bar(3, "3 chunks")
        progress.update(3)
        progress.close()
    check("the progress bar counts to the end", progress.n == 3)


# ============================================================ labels

def check_labels(folder):
    print("labels")
    check("file names match across sources", labels.file_key("A_Fall-2025-ENC-1101-RVDB-.pdf") == labels.file_key("Fall-2025-ENC-1101-RVDB-.txt"))
    check("a gold policy is CS = 1 or BP = 1", labels.gold_policy_found({"cs_present": 0, "bp_present": 1}) == 1
          and labels.gold_policy_found({"cs_present": 0, "bp_present": None}) == 0)
    headers = ["university", "sheet", "College", "Department", "File Name", "Prohibited", '"Ask Instructor"',
               "CR (1 = yes, 0 = not mentioned, * = explicitly not needed)", "BP", "CS", "Specific Context",
               "BP Lang.", "CS Lang."]
    rows = {"UNI": [["UNI", "Val_UNI", "Business", "Accounting", "A_Fall-2025-ACG-2021-RVC-.pdf", "0", "0", "1", "0", "1", "1", "n/a", "Cite AI."],
                    ["UNI", "Val_UNI", "", "", "Fall-2025-ENC-1101-U01-.pdf", "", "", "", "", "", "", "", ""]],
            "UNIC": [["UNIC", "Val_UNIC", "", "", "Fall-2025-HUM-2020-0W66-.pdf", "n/a", "n/a", "n/a", "0", "0", "n/a", "", ""]]}
    data = folder / "Labels data"                          # a made-up [01] Data with one labels.csv per university
    for university, lines in rows.items():
        path = data / settings.UNIVERSITY_NAMES[university] / settings.LABELLED_FOLDER / "labels.csv"
        path.parent.mkdir(parents=True)
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            writer.writerows(lines)
    labels.DATA = data
    try:
        gold = labels.read_gold(["UNI", "UNID"], settings.GOLD_COLUMNS)     # UNID has no labels.csv here
        check("a university with no labels.csv is skipped, not an error", True)
    except Exception:
        check("a university with no labels.csv is skipped, not an error", False)
        gold = []
    labels.DATA = settings.DATA
    check("each chosen university's labels.csv is read, other universities are not, and rows never coded are skipped", len(gold) == 1)
    check("a column is found by the start of its name (CR ...)", gold[0]["citation_required"] == 1 and gold[0]["cs_present"] == 1)
    check("n/a text becomes empty, and college and department are kept",
          gold[0]["bp_language"] == "" and gold[0]["department"] == "Accounting")
    rows = labels.attach([{"university": "UNI", "file": "Fall-2025-ACG-2021-RVC-.txt"}], gold)
    check("labels attach to their syllabus by university and file name", rows[0].get("gold_cs_present") == 1 and rows[0]["gold_text"] == "Cite AI.")
    check("and the CS and BP text are kept apart", rows[0]["gold_cs_text"] == "Cite AI." and rows[0]["gold_bp_text"] == "")

    print("metrics · step 4b against step 4")
    policy = "you may use generative tools to brainstorm but you must cite every use in your paper"
    noise = "week three covers the history of computing and ethics of technology in society"
    made_up = [   # two CS policies (one where 4b picks the right region, one where it does not), one 1-region chunk, one "no"
        {"university": "UNI", "text": noise + " " + policy, "regions": [noise, policy], "p_cs_present": 0.6, "p_bp_present": 0.2,
         "p_cs_regions": [0.3, 0.9], "p_bp_regions": [0.1, 0.2], "gold_policy_found": 1, "gold_cs_present": 1,
         "gold_bp_present": 0, "gold_cs_text": policy, "gold_bp_text": ""},
        {"university": "UNI", "text": policy + " " + noise, "regions": [policy, noise], "p_cs_present": 0.7, "p_bp_present": 0.1,
         "p_cs_regions": [0.4, 0.8], "p_bp_regions": [0.1, 0.1], "gold_policy_found": 1, "gold_cs_present": 1,
         "gold_bp_present": 0, "gold_cs_text": policy, "gold_bp_text": ""},
        {"university": "UNI", "text": policy, "regions": [policy], "p_cs_present": 0.8, "p_bp_present": 0.3,
         "p_cs_regions": [0.75], "p_bp_regions": [0.3], "gold_policy_found": 1, "gold_cs_present": 1,
         "gold_bp_present": 1, "gold_cs_text": policy, "gold_bp_text": ""},
        {"university": "UNI", "text": noise, "regions": [noise], "p_cs_present": 0.2, "p_bp_present": 0.6,
         "p_cs_regions": [0.1], "p_bp_regions": [0.6], "gold_policy_found": 1, "gold_cs_present": 0,
         "gold_bp_present": 0, "gold_cs_text": "", "gold_bp_text": ""},
    ]
    table = metrics.region_comparison(made_up).set_index("field")
    cs = table.loc["cs_present"]
    check("the AUROC is scored both ways on the same syllabi", cs["scored"] == 4 and cs["auroc_whole_chunk"] == 1.0 and cs["auroc_highest_region"] == 1.0)
    check("the region Kev scores highest is checked against the coder's region (1 of 2 right)",
          cs["policies_with_2+_regions_judged"] == 2 and cs["highest_region_is_the_coders"] == 1)
    check("1-region chunks: the largest difference from step 4", cs["one_region_chunks"] == 2 and abs(cs["one_region_largest_difference"] - 0.1) < 1e-9)


# ============================================================

def main():
    folder = Path(tempfile.mkdtemp(prefix="pipeline checks "))
    try:
        check_names()
        check_s1(folder)
        check_s3()
        check_kev(folder)
        check_s5()
        check_s6()
        check_helpers(folder)
        check_show(folder)
        check_labels(folder)
    finally:
        shutil.rmtree(folder)
    print()
    if FAILED:
        print(len(FAILED), "check(s) FAILED:")
        for what in FAILED:
            print("   " + what)
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()

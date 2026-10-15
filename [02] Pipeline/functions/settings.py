# Every shared setting of the pipeline, written once. The step files and the runners read them from here.
# What belongs to one test (which universities, which model, its cutoffs) is set in that test's runner instead ([04] Test/<test>/<test>.ipynb).

from pathlib import Path

FUNCTIONS = Path(__file__).resolve().parent     # [02] Pipeline/functions
ROOT = FUNCTIONS.parent.parent                  # the project folder: the folder that holds [01] Data to [04] Test

# ---------- where things are ----------
DATA = ROOT / "[01] Data"            # one folder per university, by full name: pdf.zip · txt/ · syllabi.csv · labelled/
LABELLED_FOLDER = "labelled"         # inside a university's folder: its hand-coded syllabi, pdf.zip · txt/ · labels.csv · labelled.jsonl
TESTS = ROOT / "[04] Test"           # one folder per test: its runner, <test>.ipynb, and its Output/
TEST_RESULTS = "test_results"        # inside a test's Output: every table the Test section makes

UNIVERSITY_NAMES = {     # short code (used in the runners and at the start of each syllabus id): full name = its folder in [01] Data
    "UNI": "University",                 # one line per university
}
TERM = "Fall 2025"       # the term every syllabus in [01] Data was collected for

# ---------- step 1: text from PDF and Word files that have no text file yet ----------
CONVERTIBLE = [".pdf", ".docx", ".doc"]   # .doc only on the Mac (macOS textutil); other files (.pptx) are listed in no text.csv
MIN_TEXT_CHARS = 1         # a file with fewer characters of text is listed in "no text.csv" and not passed on (a scan; OCR is
                           # not set up). 1 = only files with no text at all, as the original text files were made; a real stub page
                           # can have about 150 characters, so a higher number would drop syllabi like it

# ---------- step 1: subject, course and section from each university's file names ----------
# Read after the name is URL-decoded and loses its extension and a leading "A_". A name that does not fit gets blanks.
_SUBJECT, _COURSE = r"(?P<subject>[A-Z]{1,4})", r"(?P<course>\d{3,4}[A-Z]?)"
NAME_PATTERNS = {        # one pattern per university, for the way its files are named
    "UNI": r"^Fall-2025-" + _SUBJECT + "-" + _COURSE + r"-(?P<section>[^-]+)",    # Fall-2025-ENGL-1101-001-
}

# ---------- step 1: private details replaced in the text before anything else reads it ----------
SCRUB = {
    "[email]": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",                 # anything shaped like name@place.edu
    "[phone]": r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",       # anything shaped like 555-555-0100
}

# ---------- steps 2 and 4: the questions (word for word from 01 Codebook.pdf, page 2) ----------
QUESTIONS = {
    "policy_found":      "Does this syllabus state a policy on students’ use of AI tools (such as ChatGPT or other generative AI) in this course?",
    "cs_present":        "Does the text include AI policy language written by the instructor specifically for this course?",
    "bp_present":        "Does the text include standard AI policy language from the institution (university- or college-wide), rather than written for this course?",
    "prohibited":        "Does the policy prohibit, ban, or not allow students’ use of AI tools, in general or by default?",
    "specific_context":  "Does the policy allow AI for some uses or tasks but not others?",
    "ask_instructor":    "Is “ask or check with the instructor before using AI” the main guidance, with no other clear stance?",
    "citation_required": "Does the policy require students to cite, acknowledge, disclose, or document their AI use?",
}
CODE_FIELDS = ["cs_present", "bp_present", "prohibited", "specific_context", "ask_instructor", "citation_required"]

# ---------- step 3: finding the policy text ----------
KEYWORDS = [               # matched as whole words; the ones typed in capitals must be in capitals in the text
    "AI", "artificial intelligence", "ChatGPT", "GPT", "LLM", "large language model", "Claude", "Gemini", "Bard",
    "Copilot", "machine learning", "Chegg", "QuillBot", "Grammarly",
]
WINDOW = 5                 # sentences kept on each side of a keyword sentence
MAX_SENTENCE = 1000        # a "sentence" longer than this many characters is cut (tables, long lists)
BREAK = "\n\n[...]\n\n"    # put between two separate policy regions of one syllabus
ABBREVIATIONS = ["Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "e.g.", "i.e.", "etc.", "vs.", "No.", "U.S."]    # a period here does not end a sentence

# ---------- Test section: how the hand-coded labels (<University>/labelled/labels.csv) are read ----------
GOLD_COLUMNS = {               # our field: its column in labels.csv (an exact name, or the start of one)
    "cs_present":        "CS",
    "bp_present":        "BP",
    "prohibited":        "Prohibited",
    "specific_context":  "Specific Context",
    "ask_instructor":    '"Ask Instructor"',
    "citation_required": "CR",
}
GOLD_NA_COUNTS_AS_NO = False   # False: a hand-coded "n/a" on a policy syllabus is left out of that field's score

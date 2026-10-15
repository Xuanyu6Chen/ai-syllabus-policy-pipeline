# Step 4b · Regions (Kev only): Kev answers CS and BP separately for each region of the chunk, one call per region.

from server_kev import ask
from settings import BREAK, QUESTIONS

REGION_FIELDS = ["cs_present", "bp_present"]


def needs_regions(row):
    """Only syllabi that have a chunk have regions."""
    return row["chunk"] != ""


def regions_of(chunk):
    """The separate policy regions of a chunk: step 3 joined them with BREAK."""
    return chunk.split(BREAK)


def code_regions(row):
    """Step 4b for one syllabus: Kev reads each region on its own and answers CS and BP for it.
    One failed region fails the syllabus (it is retried on the next run), so every saved row has all its regions."""
    questions = {}
    for field in REGION_FIELDS:
        questions[field] = QUESTIONS[field]
    regions = regions_of(row["chunk"])
    result = {"regions": regions, "p_cs_regions": [], "p_bp_regions": []}
    for region in regions:
        answers = ask(region, questions)
        result["p_cs_regions"].append(answers["cs_present"])
        result["p_bp_regions"].append(answers["bp_present"])
    return result

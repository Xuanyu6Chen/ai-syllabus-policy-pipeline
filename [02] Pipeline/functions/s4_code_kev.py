# Step 4 · Code (Kev only): Kev reads only the chunk and answers the 6 yes/no questions in one call.

from server_kev import ask
from settings import CODE_FIELDS, QUESTIONS


def needs_coding(row):
    """Only syllabi that have a chunk go to Kev for the 6 questions."""
    return row["chunk"] != ""


def code_syllabus(row):
    """Step 4 for one syllabus: Kev reads the chunk and answers the 6 questions in one call."""
    questions = {}
    for field in CODE_FIELDS:
        questions[field] = QUESTIONS[field]
    answers = ask(row["chunk"], questions)
    result = {}
    for field in CODE_FIELDS:
        result["p_" + field] = answers[field]
    return result

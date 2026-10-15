# Step 2 · Screen (Kev only): Kev reads the whole syllabus and gives the probability that it states an AI policy.

from server_kev import ask
from settings import QUESTIONS


def screen_syllabus(row):
    """Step 2 for one syllabus: Kev reads the whole text and answers the Policy Found question."""
    answer = ask(row["text"], {"policy_found": QUESTIONS["policy_found"]})
    return {"p_policy_found": answer["policy_found"]}

# Shows a run in the runner: a status board, a header and progress bar for each step, and its results as tables.
# Display only: it reads the step files through helpers and never changes them.

import pandas

import helpers
from settings import BREAK, CODE_FIELDS, KEYWORDS

# what each block of the runner is: its title, the step file it reads, the file it writes, and whether it needs Kev
BLOCKS = {
    1:   {"title": "Step 1 · Input",            "reads": "txt/ in [01] Data", "writes": "<University>/syllabi.jsonl or labelled/labelled.jsonl in [01] Data (only when txt/ changed)", "gpu": False},
    2:   {"title": "Step 2 · Screen (Kev)",     "reads": "1 input",     "writes": "2 screen",    "gpu": True},
    3:   {"title": "Step 3 · Chunk",            "reads": "1 input",     "writes": "3 chunks",    "gpu": False},
    4:   {"title": "Step 4 · Code (Kev)",       "reads": "3 chunks",    "writes": "4 code",      "gpu": True},
    "4b": {"title": "Step 4b · Regions (Kev)",  "reads": "3 chunks",    "writes": "4b regions",  "gpu": True},
    5:   {"title": "Step 5 · Rules",            "reads": "2 · 3 · 4",   "writes": "5 decisions", "gpu": False},
    6:   {"title": "Step 6 · Export",           "reads": "1 · 5",       "writes": "<University>.csv", "gpu": False},
    "A": {"title": "Test A · Chunk check",      "reads": "1 · 3 + labels.csv", "writes": "test_results/chunk check.csv", "gpu": False},
    "B": {"title": "Test B · Scores",           "reads": "1–4b + labels.csv",  "writes": "test_results/ scores by field · cutoff tables · region comparison (.csv)", "gpu": False},
    "C": {"title": "Test C · Speed",            "reads": "2 · 4 · 4b",  "writes": "test_results/timing.csv", "gpu": False},
}
STEP_FILES = {1: "1 input", 2: "2 screen", 3: "3 chunks", 4: "4 code", "4b": "4b regions", 5: "5 decisions"}
MARKS = {"done": "✓", "current": "✓", "made": "✓", "waiting": "⏸", "stopped": "✗"}


def _out(thing):
    """Show a table (or text) the way the notebook shows it best; plain print outside a notebook.
    Every column is shown, never cut to "...", wherever the table ends up as text; row numbers are left out."""
    if isinstance(thing, pandas.DataFrame) and isinstance(thing.index, pandas.RangeIndex):
        thing = thing.copy()
        thing.index = [""] * len(thing)
    with pandas.option_context("display.max_columns", None, "display.width", 250, "display.max_colwidth", 120):
        try:
            from IPython.display import display
            display(thing)
        except ImportError:
            print(thing)


def header(block, model=None):
    """The first lines of a block: its title, what it reads and writes, and whether it needs a GPU."""
    info = BLOCKS[block]
    title = "━━ " + info["title"] + " "
    print(title + "━" * max(3, 78 - len(title)))
    reads = info["reads"]
    if reads in STEP_FILES.values():
        reads = reads + " (" + str(len(helpers.read(reads))) + " syllabi)"
    line = "reads " + reads + "  →  writes " + info["writes"]
    if info["gpu"]:
        line = line + "  ·  needs a GPU"
    if model:
        line = line + "  ·  model " + model
    print(line)


def bar(total, label):
    """A live progress bar for a step (helpers.run_step calls it): count, time so far, time left, speed."""
    from tqdm.auto import tqdm
    return tqdm(total=total, desc=label, unit=" syllabi", dynamic_ncols=True)


def report(result):
    """One line on how a step went, from what helpers.run_step / build_input / write give back."""
    if result is None:
        return
    mark = MARKS.get(result["state"], "·")
    line = mark + " " + str(result["done"]) + " of " + str(result["total"]) + " done"
    if result.get("errors"):
        line = line + " · " + str(len(result["errors"])) + " errors"
    elif result["state"] in ("done", "stopped"):
        line = line + " · 0 errors"
    if result.get("seconds") is not None and result.get("new"):
        line = line + " · " + str(result["seconds"]) + " s (" + str(round(result["seconds"] / result["new"], 2)) + " s per syllabus)"
    if result["state"] == "current":
        line = line + " · already made, nothing changed"
    if result.get("why"):
        line = line + " · " + result["why"]
    print(line)
    if result.get("changed"):
        print("  redone, because this changed:", ", ".join(result["changed"]))
    if result.get("errors"):
        print("  syllabi with errors (run this block again to retry them):", ", ".join(list(result["errors"])[:10]))


def waiting(reasons):
    """A block that cannot run yet, and why."""
    print("⏸ waiting for: " + "; ".join(reasons))


def tried(results):
    """The try-first table: a few syllabi sent to Kev before the full run, with their answers and time."""
    print("Tried first:")
    _out(pandas.DataFrame(results))


def input_summary(rows, universities, result=None):
    """Step 1's results: per university, its jsonl (built now or already current), how many syllabi, how long they
    are, and how many names fit no pattern."""
    jsonl = {}
    for line in (result or {}).get("universities", []):
        jsonl[line["university"]] = line
    lines = []
    for university in universities:
        mine = [row for row in rows if row["university"] == university]
        lengths = sorted(row["n_chars"] for row in mine)
        state = jsonl.get(university, {}).get("state", "")
        if not lengths:
            lines.append({"university": university, "jsonl": state, "syllabi": 0})
            continue
        lines.append({"university": university, "jsonl": state, "syllabi": len(mine), "chars_shortest": lengths[0],
                      "chars_middle": lengths[len(lengths) // 2], "chars_longest": lengths[-1],
                      "name_fits_no_pattern": sum(1 for row in mine if row["subject"] == "")})
    _out(pandas.DataFrame(lines))
    if result and result.get("duplicates"):
        print(result["duplicates"], "exact duplicate texts dropped (listed in each jsonl's record.json)")
    for line in (result or {}).get("universities", []):
        print("  ", line["university"] + ":", "[01] Data/" + line["jsonl"],
              "· built now, because of: " + ", ".join(line["changed"]) if line["state"] == "built" else "· already current")


def probabilities(name):
    """Steps 2 and 4: the spread of each probability Kev gave, and the time per syllabus."""
    rows = helpers.read(name)
    if not rows:
        return
    lines = []
    for field in rows[0]:
        if not field.startswith("p_"):
            continue
        values = sorted(row[field] for row in rows if isinstance(row.get(field), (int, float)))
        lines.append({"question": field[2:], "syllabi": len(values), "lowest": round(values[0], 3),
                      "middle": round(values[len(values) // 2], 3), "highest": round(values[-1], 3),
                      "0.5_or_more": sum(1 for value in values if value >= 0.5)})
    _out(pandas.DataFrame(lines))
    times = sorted(value for row in rows for field, value in row.items() if field.endswith("_ms"))
    if times:
        print("time per syllabus: middle", round(times[len(times) // 2] / 1000, 2), "s · all together",
              round(sum(times) / 60000, 1), "min")


def chunks_summary(rows):
    """Step 3's results: how many syllabi have a chunk, in how many separate regions, how long, and which keywords."""
    with_chunk = [row for row in rows if row["chunk"] != ""]
    regions = [row["chunk"].count(BREAK) + 1 for row in with_chunk]
    sizes = sorted(row["chunk_chars"] for row in with_chunk)
    line = {"syllabi": len(rows), "with_a_chunk": len(with_chunk),
            "1_region": regions.count(1), "2_regions": regions.count(2), "3+_regions": sum(1 for n in regions if n >= 3)}
    if sizes:
        line.update({"chars_middle": sizes[len(sizes) // 2], "chars_largest": sizes[-1]})
    _out(pandas.DataFrame([line]))
    counts = [{"keyword": term, "syllabi": sum(1 for row in rows if term in row["keywords"])} for term in KEYWORDS]
    print("Syllabi with each keyword in their chunk:")
    _out(pandas.DataFrame(counts).set_index("keyword").T)


def regions_summary(name):
    """Step 4b's results: how many regions Kev read, and how many it scored 0.5 or more for CS and for BP."""
    rows = helpers.read(name)
    if not rows:
        return
    lines = []
    for field, short in [("cs_present", "cs"), ("bp_present", "bp")]:
        values = sorted(value for row in rows for value in row["p_" + short + "_regions"])
        lines.append({"question": field, "syllabi": len(rows), "regions": len(values), "lowest": round(values[0], 3),
                      "middle": round(values[len(values) // 2], 3), "highest": round(values[-1], 3),
                      "regions_0.5_or_more": sum(1 for value in values if value >= 0.5),
                      "syllabi_with_one_0.5_or_more": sum(1 for row in rows if max(row["p_" + short + "_regions"]) >= 0.5)})
    _out(pandas.DataFrame(lines))
    times = sorted(row["regions_ms"] for row in rows if "regions_ms" in row)
    if times:
        print("time per syllabus (all its regions): middle", round(times[len(times) // 2] / 1000, 2), "s · all together",
              round(sum(times) / 60000, 1), "min")


def chunk(syllabus_id):
    """Print one syllabus's chunk, to read it. On Colab the printed text is saved with the notebook in Drive;
    Edit > Clear all outputs removes it."""
    for row in helpers.join(["1 input", "3 chunks"]):
        if row["id"] == syllabus_id:
            print(row["id"], "|", row["file"], "|", row["n_chars"], "characters | keywords:", row.get("keywords"))
            print("-" * 80)
            print(row.get("chunk") or "(no chunk: no keyword in this syllabus)")
            return
    print("No syllabus with id", syllabus_id)


def decisions_summary(decisions):
    """Step 5's results: how many 1 / 0 / n/a for each field, and how many syllabi go to the review queue."""
    lines = []
    for field in ["policy_found"] + CODE_FIELDS:
        answers = [str(decision[field]) for decision in decisions]
        lines.append({"field": field, "1": answers.count("1"), "0": answers.count("0"), "n/a": answers.count("n/a")})
    _out(pandas.DataFrame(lines))
    print(sum(1 for decision in decisions if decision["review"] != ""), "syllabi in the review queue")


def exports(saved):
    """Step 6's results: the CSV saved for each university, and its rows."""
    _out(pandas.DataFrame([{"university": university, "rows": rows, "file": university + ".csv"}
                           for university, rows in saved]))


def chunk_check(table):
    """Test A's results: how often the chunk holds the policy text the coders copied, and the ones it does not."""
    if len(table) == 0:
        print("No hand-coded policy syllabi in this set.")
        return
    counts = table["verdict"].value_counts()
    _out(pandas.DataFrame([{"policy_syllabi": len(table), "cannot_judge": counts.get("cannot judge", 0),
                            "full": counts.get("full", 0), "partial": counts.get("partial", 0),
                            "missed": counts.get("missed", 0)}]))
    print("cannot judge = the copied policy text is not fully in the text file")
    misses = table[table["verdict"].isin(["partial", "missed"])]
    if len(misses) > 0:
        print("Partial or missed:")
        _out(misses)


def status_board(gpu_up, cutoffs_set, universities):
    """Where this test stands, step by step: made, how many rows, errors, time, and what a step waits for."""
    lines = []
    for number, name in STEP_FILES.items():
        status = helpers.status(name)
        state = status["state"]
        if state == "not made yet" and BLOCKS[number]["gpu"] and not gpu_up:
            state = "waiting: needs a GPU"
        if state == "not made yet" and number == 5 and not cutoffs_set:
            state = "waiting: CUTOFFS empty"
        mark = "✓ " if state == "ready" else "⏸ "
        lines.append({"step": BLOCKS[number]["title"].replace(" (Kev)", ""), "state": mark + state,
                      "rows": status["rows"], "errors": status["errors"], "seconds": status["seconds"],
                      "made": status["made"]})
    lines = [{key: ("" if value is None else value) for key, value in line.items()} for line in lines]
    saved = [university for university in universities if (helpers.OUTPUT / (university + ".csv")).exists()]
    lines.append({"step": "Step 6 · Export", "state": ("✓ " + ", ".join(u + ".csv" for u in saved)) if saved else "⏸ not made yet",
                  "rows": "", "errors": "", "seconds": "", "made": ""})
    _out(pandas.DataFrame(lines, dtype=object).set_index("step"))

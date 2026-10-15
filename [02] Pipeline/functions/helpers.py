# Plumbing for the runners: reads and writes the step files, runs a step over every syllabus, and remembers what
# produced each file. Nothing in here decides a result, and nothing in here is specific to one model.
# It prints nothing: each step gives back a report (what it did), and show.py shows it.

import hashlib
import inspect
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent      # [02] Pipeline/functions: the pipeline's own functions live here
ON_COLAB = "google.colab" in sys.modules

OUTPUT = None       # the test's Output folder: step files and results (filled in by start)
DATA = None         # [01] Data: step 1's jsonl files live there, one per university (filled in by start)
INPUT = "1 input"   # step 1's name: its rows are read from those jsonl files, which its record lists
STEPS = {}          # what each run_step call was asked to do, so ready() can check it again later
_CACHE = {}         # step files already read: file -> (its size and time when read, its rows)


# ============================================================ 1. folders and files

def start(output_folder, data_folder):
    """Say where this run keeps its files (the test's Output folder) and where step 1's jsonl files are ([01] Data)."""
    global OUTPUT, DATA
    OUTPUT = Path(output_folder)
    DATA = Path(data_folder)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    STEPS.clear()


def file_of(name):
    """The step file with this name, for example Output/2 screen.jsonl"""
    return OUTPUT / (name + ".jsonl")


def files_of(name):
    """The files a step's rows are in: step 1's jsonl files in [01] Data (as its record lists them), or Output/<name>.jsonl."""
    if name == INPUT:
        record = read_record(INPUT)
        return [DATA / where for where in record.get("files", [])] if record else []     # an older record lists none
    return [file_of(name)]


def made(name):
    """True when a step's rows exist: its record and every one of its files."""
    files = files_of(name)
    return read_record(name) is not None and bool(files) and all(path.exists() for path in files)


def read(name):
    """Read a step's rows as a list. Each row is a dictionary. A missing file gives an empty list."""
    rows = []
    for path in files_of(name):
        rows = rows + _read_file(path)
    return rows


def _read_file(path):
    if not path.exists():
        return []
    stamp = (path.stat().st_size, path.stat().st_mtime)
    if path not in _CACHE or _CACHE[path][0] != stamp:      # not read yet, or the file changed since
        rows = []
        with open(path, encoding="utf-8") as file:
            for line in file:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:                # a half-written last line, left by a run that was cut off
                    pass
        _CACHE[path] = (stamp, rows)
    return [dict(row) for row in _CACHE[path][1]]           # copies, so the caller can add fields freely


def write(name, rows, made_from=()):
    """Write a step file, and note which versions of other step files it was made from."""
    with open(file_of(name), "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    versions = _versions(made_from)
    record = {"step": name, "made": _now(), "where": _where(), "rows": len(rows), "made_from": versions,
              "version": _version({}, {}, versions)}
    _write_record(name, record)
    return {"step": name, "state": "done", "done": len(rows), "total": len(rows), "new": len(rows)}


def join(names):
    """One row per syllabus of the first file, with the fields of the other files added to it (matched by id)."""
    rows = read(names[0])
    by_id = {}
    for row in rows:
        by_id[row["id"]] = row
    for name in names[1:]:
        for extra in read(name):
            if extra["id"] in by_id:
                by_id[extra["id"]].update(extra)
    return rows


def read_record(name):
    """The record of a step file (what produced it), or None when there is none."""
    return _all_records().get(name)


def _all_records():
    """All records are kept together in Output/records.json"""
    path = OUTPUT / "records.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_record(name, record):
    records = _all_records()
    records[name] = record
    (OUTPUT / "records.json").write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")


def _versions(names):
    """The version of each named step file, as written in its record."""
    versions = {}
    for name in names:
        record = read_record(name)
        versions[name] = record.get("version") if record else None
    return versions


def _version(functions, settings, made_from):
    """A short code that stands for everything a step file was made from: the functions, the settings and the
    files it read. Same ingredients give the same code, so undoing a change makes earlier results valid again."""
    ingredients = json.dumps([functions, settings, made_from], sort_keys=True)
    return hashlib.sha1(ingredients.encode("utf-8")).hexdigest()[:12]


def _now():
    return datetime.now().isoformat(sep=" ", timespec="microseconds")


def _where():
    return "Colab" if ON_COLAB else "Mac"


# ============================================================ 2. remembering what produced a file

def _source_lines(function):
    """The code of a function as a list of lines, leaving out blank lines and comment-only lines."""
    try:
        text = inspect.getsource(function)
    except (OSError, TypeError):
        return ["(code not available)"]
    lines = []
    for line in text.split("\n"):
        if line.strip() == "" or line.strip().startswith("#"):
            continue
        lines.append(line.rstrip())
    return lines


def _names_used(code):
    """Every name a piece of code refers to."""
    names = set(code.co_names)
    for constant in code.co_consts:
        if inspect.iscode(constant):
            names = names | _names_used(constant)
    return names


def _plain(value):
    """A setting in a form that can be saved and compared. Folders are left out: only what they hold matters."""
    if isinstance(value, Path):
        return "(a folder or file)"
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value))


def depends_on(functions):
    """What a step depends on: its functions, the pipeline functions they call, and the ALL-CAPS settings they read."""
    found_functions = {}
    found_settings = {}
    waiting = list(functions)
    while waiting:
        function = waiting.pop()
        if function.__name__ in found_functions:
            continue
        found_functions[function.__name__] = _source_lines(function)
        names = function.__globals__                     # every name the function's own file can see
        for name in _names_used(function.__code__):
            value = names.get(name)
            if inspect.isfunction(value) and _ours(value, functions[0]):
                waiting.append(value)
            elif name.isupper() and name in names:
                found_settings[name] = _plain(value)
    return found_functions, found_settings


def _ours(function, first):
    """True for a pipeline function: written in a file in this folder, or in the same place as `first`."""
    if function.__module__ == first.__module__:
        return True
    try:
        return Path(inspect.getfile(function)).resolve().parent == HERE
    except TypeError:                                    # built into Python: not ours
        return False


def what_changed(record, functions, settings, made_from):
    """Compare a record with what the notebook says now. Gives the list of things that differ (empty = still current)."""
    changed = []
    for name in sorted(set(record.get("functions", {})) | set(functions)):
        if record.get("functions", {}).get(name) != functions.get(name):
            changed.append("function " + name)
    for name in sorted(set(record.get("settings", {})) | set(settings)):
        if record.get("settings", {}).get(name) != settings.get(name):
            changed.append("setting " + name)
    for name in made_from:
        if record.get("made_from", {}).get(name) != made_from[name]:
            changed.append("file '" + name + "' was made with other settings")
    return changed


def _current(function):
    """The newest definition of a function (its file may have been reloaded since it was first passed in)."""
    if function is None:
        return None
    return function.__globals__.get(function.__name__, function)


# ============================================================ 3. running the steps

def build_input(step1, choice):
    """Step 1. For each university of the test, makes sure its jsonl in [01] Data is current, and points the test at
    those files (no copy in Output). A jsonl is rebuilt only when its text files (names and sizes), step 1's code or
    settings, or (labelled.jsonl) its labels.csv changed. A rebuilt jsonl: ids like UNI-0001 by file name, exact
    duplicate texts dropped, and for the labelled set each row's hand-coded answers as `labels`.
    step1: the step's file (s1_input), which gives list_files, load_syllabus, jsonl_path, add_labels, labels_stamp.
    choice: the test's own settings that pick its syllabi, {"UNIVERSITIES": [...], "LABELLED_ONLY": True / False}.
    Gives back a report: state ("current" or "done"), rows, and one line per university (its jsonl, built or current)."""
    labelled = choice["LABELLED_ONLY"]
    functions, settings = depends_on([step1.list_files, step1.load_syllabus])
    label_functions, label_settings = depends_on([step1.add_labels]) if labelled else ({}, {})
    started = time.time()
    universities = []
    files = []
    versions = {}
    for university in choice["UNIVERSITIES"]:
        path = step1.jsonl_path(university, labelled)
        sources = step1.list_files([university], labelled)
        text_files = _version({}, {}, [[source["where"], source["size"]] for source in sources])
        version = _version(functions, settings, {"text files": text_files})
        labels_version = None
        if labelled:
            labels_version = _version(label_functions, label_settings, {"labels.csv": step1.labels_stamp(university)})
        record_path = path.with_name(path.stem + " record.json")
        old = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else None
        where = str(path.relative_to(DATA))
        files.append(where)
        versions[where] = version
        if old is not None and path.exists() and old["version"] == version and old.get("labels_version") == labels_version:
            universities.append({"university": university, "jsonl": where, "state": "current", "rows": old["rows"],
                                 "duplicates": len(old["duplicates_dropped"])})
            continue

        changed = ["no jsonl yet"] if old is None or not path.exists() else what_changed(old, functions, settings, {})
        if old is not None and old.get("text_files") != text_files:
            changed.append("the text files in txt/")
        if old is not None and old.get("labels_version") != labels_version:
            changed.append("labels.csv or how it is read")
        rows = []
        duplicates = []
        first_with_text = {}        # text -> id of the first syllabus that has exactly this text
        for source in sources:
            row = {"id": university + "-" + str(len(rows) + len(duplicates) + 1).zfill(4)}
            row.update(step1.load_syllabus(source))
            same_text = re.sub(r"\s+", " ", row["text"]).strip().lower()
            if same_text in first_with_text:
                duplicates.append({"file": row["file"], "same_text_as": first_with_text[same_text]})
                continue
            first_with_text[same_text] = row["id"]
            rows.append(row)
        if labelled:
            rows = step1.add_labels(university, rows)
        with open(path, "w", encoding="utf-8") as output:
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
        record = {"jsonl": where, "made": _now(), "where": _where(), "rows": len(rows), "duplicates_dropped": duplicates,
                  "functions": functions, "settings": settings, "text_files": text_files, "labels_version": labels_version,
                  "version": version}
        record_path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
        universities.append({"university": university, "jsonl": where, "state": "built", "rows": len(rows),
                             "duplicates": len(duplicates), "changed": changed})

    total = sum(line["rows"] for line in universities)
    built = [line for line in universities if line["state"] == "built"]
    record = {"step": INPUT, "made": _now(), "where": _where(), "rows": total, "files": files, "versions": versions,
              "settings": _plain(choice), "version": _version({}, _plain(choice), versions)}
    _write_record(INPUT, record)
    report = {"step": INPUT, "state": "done" if built else "current", "done": total, "total": total,
              "universities": universities, "duplicates": sum(line["duplicates"] for line in universities)}
    if built:
        report.update({"new": sum(line["rows"] for line in built), "seconds": round(time.time() - started, 1)})
    return report


def _state(name):
    """Where a step stands: which syllabi it covers, which are done, and whether its file is still current."""
    step = STEPS[name]
    function = _current(step["function"])
    only = _current(step["only"])
    starting = [function] if only is None else [function, only]
    functions, settings = depends_on(starting)
    if step["model"] is not None:
        settings["MODEL"] = step["model"]                       # other model, other answers
    made_from = _versions([step["reads"]])

    wanted = []
    for row in read(step["reads"]):
        if only is None or only(row):
            wanted.append(row)

    record = read_record(name)
    exists = made(name)
    changed = what_changed(record, functions, settings, made_from) if exists else []
    done = set(row["id"] for row in read(name)) if exists else set()
    todo = [row for row in wanted if row["id"] not in done]
    return {"function": function, "functions": functions, "settings": settings, "made_from": made_from,
            "wanted": wanted, "todo": todo, "exists": exists, "changed": changed, "record": record}


def run_step(name, function, reads, only=None, server=None, model=None, progress=None):
    """Apply `function` to every syllabus in the step file `reads`, and save each result in the step file `name`.
    - Syllabi already done are skipped, so a run that was cut off continues where it stopped.
    - If a setting or function this step uses changed since the file was made, the step starts over.
    - only: a function that answers True / False for each syllabus: does it take part in this step?
    - server, model: the step asks a model (server_kev, and the model it runs), so it only runs where that server is
      up (a GPU runtime). Its answers are noted with the model, and another model makes the step start over.
    - progress: makes a progress bar, progress(how many to do, name) (show.bar); None = no bar.
    Gives back a report: state ("current", "done", "waiting" or "stopped"), done and total, the new ones, errors,
    seconds, what changed, and why it waits."""
    STEPS[name] = {"function": function, "reads": reads, "only": only, "server": server, "model": model}
    if not made(reads):
        return {"step": name, "state": "waiting", "done": 0, "total": 0, "why": "'" + reads + "' not made yet"}
    state = _state(name)
    can_run = server is None or server.is_up()
    total = len(state["wanted"])
    done = total - len(state["todo"])

    if state["changed"]:
        if not can_run:
            return {"step": name, "state": "waiting", "done": done, "total": total, "changed": state["changed"],
                    "why": "out of date, and the model is not running here (to keep these answers anyway: "
                           "helpers.keep_anyway('" + name + "'))"}
        if server is not None:      # model answers cost GPU time: set the old file aside instead of deleting it
            shutil.move(str(file_of(name)), str(OUTPUT / ("old " + name + ".jsonl")))
        state["exists"] = False
        state["todo"] = state["wanted"]
        done = 0                                        # starting over: nothing counts as done

    if not state["todo"] and state["exists"]:
        return {"step": name, "state": "current", "done": total, "total": total}
    if not can_run:
        return {"step": name, "state": "waiting", "done": done, "total": total, "why": "the model needs a GPU runtime"}

    record = {"step": name, "made": _now(), "where": _where(), "functions": state["functions"],
              "settings": state["settings"], "made_from": state["made_from"],
              "version": _version(state["functions"], state["settings"], state["made_from"])}
    if not state["exists"]:
        open(file_of(name), "w").close()                # start an empty file
    else:
        _drop_half_line(name)
    if server is not None:
        record["model_server"] = server.details()
    _write_record(name, record)

    todo = state["todo"]
    time_field = name.split(" ", 1)[1] + "_ms"          # for example "screen_ms": milliseconds this syllabus took
    errors = {}
    errors_in_a_row = 0
    started = time.time()
    stopped = False
    bar = progress(len(todo), name) if progress else None
    with open(file_of(name), "a", encoding="utf-8") as output:
        for row in todo:
            clock = time.time()
            try:
                result = state["function"](row)
            except Exception as problem:
                if server is None:
                    raise                               # a mistake in the code: show it
                errors[row["id"]] = str(problem)[:300]  # a problem talking to the model: note it and go on
                errors_in_a_row = errors_in_a_row + 1
                if bar:
                    bar.update(1)
                if errors_in_a_row >= 5:
                    stopped = True
                    break
                continue
            errors_in_a_row = 0
            line = {"id": row["id"]}
            line.update(result)
            line[time_field] = round((time.time() - clock) * 1000, 1)
            output.write(json.dumps(line, ensure_ascii=False) + "\n")
            output.flush()
            if bar:
                bar.update(1)
    if bar:
        bar.close()

    record["rows"] = len(read(name))
    record["errors"] = errors
    record["seconds"] = round(time.time() - started, 1)
    _write_record(name, record)
    result = {"step": name, "state": "stopped" if stopped else "done", "done": record["rows"], "total": total,
              "new": record["rows"] - done, "errors": errors, "seconds": record["seconds"], "changed": state["changed"]}
    if stopped:
        result["why"] = "stopped after 5 errors in a row; the last one: " + list(errors.values())[-1]
    return result


def _drop_half_line(name):
    """A run cut off while writing can leave half a line at the end of a step file. Keep only the whole lines, so
    the next answer starts on a line of its own instead of being glued to the half line (and lost)."""
    path = file_of(name)
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        path.write_bytes(data[:data.rfind(b"\n") + 1])


def _problem(name):
    """Why a step file cannot be used yet, as a short text. An empty text means it is complete and current."""
    if not made(name):
        return "not made yet"
    if name in STEPS:
        state = _state(name)
        if state["changed"]:
            return "out of date: " + ", ".join(state["changed"])
        if state["todo"]:
            done = len(state["wanted"]) - len(state["todo"])
            return str(done) + " of " + str(len(state["wanted"])) + " done"
        return ""
    record = read_record(name)
    for other, version in record.get("made_from", {}).items():
        other_record = read_record(other)
        if other_record is None or other_record.get("version") != version:
            return "out of date: '" + other + "' was made with other settings"
    return ""


def waiting_for(names):
    """What the named step files still lack, one text each, like "'2 screen' (not made yet)". Empty = all ready."""
    waiting = []
    for name in names:
        problem = _problem(name)
        if problem:
            waiting.append("'" + name + "' (" + problem + ")")
    return waiting


def ready(names):
    """True when every named step file is complete and current."""
    return not waiting_for(names)


def status(name):
    """Where one step file stands, for the status board: its state ("ready" or the problem), rows, errors,
    seconds and when it was made."""
    record = read_record(name) if OUTPUT is not None else None
    problem = _problem(name)
    if record is None or not made(name):
        return {"state": "not made yet", "rows": None, "errors": None, "seconds": None, "made": None}
    return {"state": problem or "ready", "rows": len(read(name)), "errors": len(record.get("errors", {})),
            "seconds": record.get("seconds"), "made": (record.get("made", "")[:16] + " (" + record.get("where", "") + ")") if record.get("made") else ""}


def keep_anyway(name):
    """Accept a step file as current even though the notebook changed since it was made.
    Use it only when the change cannot affect the results. Run the step's block first."""
    state = _state(name)
    record = state["record"]
    record["functions"] = state["functions"]
    record["settings"] = state["settings"]
    record["made_from"] = state["made_from"]
    record["version"] = _version(state["functions"], state["settings"], state["made_from"])
    record["kept_anyway"] = _now()
    _write_record(name, record)
    return {"step": name, "state": "current", "done": len(read(name)), "total": len(state["wanted"]),
            "why": "kept as it is and marked current"}


# ============================================================ 4. small tools

def scrub(text, patterns):
    """Replace private details. patterns = {"[email]": "pattern for an email", ...}"""
    for label, pattern in patterns.items():
        text = re.sub(pattern, label, text)
    return text


def shortest_and_longest(rows, how_many, length="n_chars"):
    """The shortest and the longest syllabi (by the field `length`): the ones most likely to show a problem
    before a long run."""
    by_length = sorted(rows, key=lambda row: row[length])
    if len(by_length) <= 2 * how_many:
        return by_length
    return by_length[:how_many] + by_length[-how_many:]


def try_first(function, rows, length="n_chars"):
    """Run a step's function on a few syllabi before the full run, without saving anything. One line each:
    id, length, the answer (or the error), seconds."""
    results = []
    for row in rows:
        clock = time.time()
        try:
            answer = function(row)
        except Exception as problem:                       # show the problem and go on to the next syllabus
            answer = "ERROR: " + str(problem)[:150]
        results.append({"id": row["id"], "characters": row[length], "answer": answer,
                        "seconds": round(time.time() - clock, 1)})
    return results


def save_output(name, table, folder=""):
    """Save a results table as Output/<name>.csv, or Output/<folder>/<name>.csv (the Test section: test_results)."""
    where = OUTPUT / folder
    where.mkdir(exist_ok=True)
    table.to_csv(where / (name + ".csv"), index=False)

# Kev only. Starts Kev (the yes/no model) as a small server on this machine's GPU, checks that it answers, and sends
# it questions. Does nothing without a GPU.
# Every model's server file gives the same four functions, so the steps can use it: start(model), is_up(),
# ask(text, questions) -> the probability of "yes" for each question, and details().

import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

URL = "http://127.0.0.1:8009/v1/systemone"     # Kev runs as a small server on the same machine as the runner
FOLDER = str(Path.home() / "kev")                # where Kev's own code is downloaded (the machine's own disk, not Drive)
LOG = str(Path.home() / "kev.log")               # everything the Kev server prints goes here
_url = None                 # the address questions are sent to (filled in by start)
_process = None             # the running server
_details = {}               # which model and version is running (saved with every Kev result)


def is_up(url=None):
    """True when the Kev server answers."""
    address = url or _url
    if address is None:
        return False
    parts = urlparse(address)
    try:
        return requests.get(parts.scheme + "://" + parts.netloc + "/v1/models", timeout=2).ok
    except requests.exceptions.RequestException:
        return False


def start(model):
    """Start the Kev server with one model and wait until it answers. The first start downloads about 8 GB.
    model: a Hugging Face name (jaredpalmer/kev-4b) or the folder of a fine-tuned checkpoint."""
    global _url, _process, _details
    _url = URL
    if is_up():
        print("Kev is already running.")
        if not _details:
            _details = {"model": model}
        return
    if shutil.which("nvidia-smi") is None:
        print("No GPU on this machine, so Kev is not started and the Kev steps (2, 4, 4b) will wait.")
        print("In Colab: Runtime > Change runtime type > pick a GPU, then Run all again.")
        return

    if not Path(FOLDER).exists():
        _run("pip install -q uv")
        _run("git clone -q https://github.com/jaredpalmer/kev.git " + FOLDER)
        _run("uv sync -q --extra serve", folder=FOLDER)

    port = str(urlparse(URL).port)
    command = ["uv", "run", "--extra", "serve", "python", "-m", "kev.serve", "--run", model, "--port", port]
    _process = subprocess.Popen(command, cwd=FOLDER, stdout=open(LOG, "w"), stderr=subprocess.STDOUT)

    print("Starting Kev. This takes a few minutes the first time.")
    for attempt in range(240):                      # wait up to 20 minutes
        if _process.poll() is not None:
            raise RuntimeError("Kev stopped while starting. The end of " + LOG + ":\n" + _end_of_log())
        if is_up():
            _details = _read_details(model)
            print("Kev is ready:", _details)
            return
        time.sleep(5)
    raise TimeoutError("Kev did not answer after 20 minutes. The end of " + LOG + ":\n" + _end_of_log())


def details():
    """Which model and version is running."""
    return _details


def ask(text, questions):
    """Send one text and some yes/no questions to Kev. Gives back Kev's probability of "yes" for each question."""
    body = {"state": text, "model": "kev-latest", "questions": {}}
    for name, question in questions.items():
        body["questions"][name] = {"type": "noul", "instructions": question}     # "noul" is Kev's name for a yes/no question
    reply = requests.post(_url, json=body, timeout=600)
    reply.raise_for_status()                                                      # stop here if Kev reported an error
    answers = reply.json()["answers"]
    probabilities = {}
    for name in questions:
        probabilities[name] = float(answers[name]["noul"])
    return probabilities


def _run(command, folder=None):
    subprocess.run(command, shell=True, check=True, cwd=folder)


def _end_of_log():
    if not Path(LOG).exists():
        return "(no log)"
    return "\n".join(Path(LOG).read_text(errors="replace").split("\n")[-15:])


def _read_details(model):
    """The model's exact version, read from the server's own start-up line, and the version of Kev's code."""
    found = {"model": model}
    text = Path(LOG).read_text(errors="replace") if Path(LOG).exists() else ""
    match = re.search(r"snapshots/([0-9a-f]{8,})", text)
    if match:
        found["model_version"] = match.group(1)[:12]
    try:
        code = subprocess.run(["git", "-C", FOLDER, "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
        found["kev_code_version"] = code.stdout.strip()
    except OSError:
        pass
    return found

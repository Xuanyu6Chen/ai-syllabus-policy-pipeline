# Step 3 · Chunk: finds the policy text with plain Python, every keyword sentence plus WINDOW sentences on each side.

import re

from settings import ABBREVIATIONS, BREAK, KEYWORDS, MAX_SENTENCE, WINDOW

_made = {}      # the compiled keyword patterns, made once for each keyword list (see _patterns)


def _patterns(keywords):
    """The keyword patterns for this keyword list, compiled once: one per keyword, and one that finds any of them.
    Whole words only: no letter or digit may touch a keyword on either side; a plural "s" is allowed. A keyword typed
    in capitals must be in capitals in the text; the others match in any case."""
    if keywords not in _made:
        each = []
        exact = []
        any_case = []
        for term in keywords:
            body = re.escape(term) + "s?"
            if term.isupper():
                each.append((term, re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])")))
                exact.append(body)
            else:
                each.append((term, re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.IGNORECASE)))
                any_case.append(body)
        choices = exact + ["(?i:" + "|".join(any_case) + ")"] if any_case else exact
        any_keyword = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(choices) + r")(?![A-Za-z0-9])")
        _made[keywords] = (each, any_keyword)
    return _made[keywords]


def keywords_in(text):
    """Which keywords does this text contain? Whole words only, so "LLM" does not match inside "enrollment"."""
    each = _patterns(tuple(KEYWORDS))[0]
    return [term for term, pattern in each if pattern.search(text)]


def has_keyword(text):
    """Does this text contain any keyword? The same rule as keywords_in, in one search instead of one per keyword."""
    any_keyword = _patterns(tuple(KEYWORDS))[1]
    return any_keyword.search(text) is not None


def glue_lines(text):
    """The text files break every line at the page margin. This puts lines that belong together back together.
    A line continues on the next one when the next line starts in lower case,
    or when the line runs to the margin without ending in . ! ? :"""
    lines = [line.strip() for line in text.split("\n")]
    lengths = sorted(len(line) for line in lines if line != "")
    if not lengths:
        return []
    margin = lengths[int(0.9 * len(lengths))]              # the usual full line width in this file

    pieces = []
    current = ""
    for position, line in enumerate(lines):
        if line == "":                                     # a blank line always ends a piece
            if current != "":
                pieces.append(current)
                current = ""
            continue

        if current == "":
            current = line
        elif current.endswith("-") and line[0].islower():  # a word split by a hyphen at the margin
            current = current + line
        else:
            current = current + " " + line

        if position + 1 < len(lines):
            next_line = lines[position + 1]
        else:
            next_line = ""
        reaches_margin = len(line) >= 0.75 * margin and not line.endswith((".", "!", "?", ":"))
        continues = next_line != "" and (next_line[0].islower() or reaches_margin)
        if not continues or len(current) > MAX_SENTENCE:
            pieces.append(current)
            current = ""
    if current != "":
        pieces.append(current)
    return pieces


def split_sentences(text):
    """Cut a syllabus into sentences: after . ! ? when a capital letter, a digit or a quote comes next."""
    sentences = []
    abbreviations = tuple(" " + short for short in ABBREVIATIONS)
    for piece in glue_lines(text):
        start = 0
        # each match is the end of a sentence ( . ! ? and maybe a closing quote ) followed by the start of a new one
        for end in re.finditer(r'[.!?]["”’)]*(?=\s+[A-Z0-9"“(\[])', piece):
            candidate = piece[start:end.end()].strip()
            is_abbreviation = (" " + candidate).endswith(abbreviations)
            is_list_number = len(candidate) <= 4           # "1." or "a)" at the start of a list item
            if is_abbreviation or is_list_number:
                continue
            sentences.append(candidate)
            start = end.end()
        last = piece[start:].strip()
        if last != "":
            sentences.append(last)
    return sentences


def find_chunk(text):
    """The policy text of one syllabus: every sentence with a keyword, plus WINDOW sentences on each side.
    Regions that touch or overlap are merged. A syllabus with no keyword gives an empty chunk."""
    sentences = split_sentences(text)

    regions = []                                           # each region is [first sentence, last sentence]
    for position, sentence in enumerate(sentences):
        if not has_keyword(sentence):
            continue
        first = max(0, position - WINDOW)
        last = min(len(sentences) - 1, position + WINDOW)
        if regions and first <= regions[-1][1] + 1:        # touches the region before it: make that one longer
            regions[-1][1] = last
        else:
            regions.append([first, last])

    parts = []
    for first, last in regions:
        parts.append(" ".join(sentences[first:last + 1]))
    return BREAK.join(parts)


def chunk_syllabus(row):
    """Step 3 for one syllabus."""
    chunk = find_chunk(row["text"])
    return {"chunk": chunk, "chunk_chars": len(chunk), "keywords": keywords_in(chunk)}

#!/usr/bin/env python3
"""Add generated pages to an index that someone else wrote, or refuse to.

    import wire_toctree
    changed, note = wire_toctree.wire(index_path, ["architecture/key_modules"])

This is the one place in the pipeline that edits a file a person wrote, so the rules are
narrower than anywhere else:

    * entries already listed are left alone, so wiring twice is wiring once
    * everything outside the entry list survives byte for byte -- prose, options,
      comments, the order of what was already there
    * an index this cannot parse with confidence is refused, not rewritten. A file it
      does not understand is exactly the file it must not touch
    * with no toctree at all, it refuses too. Inventing one means choosing where in
      someone's document it goes, and that is not a choice a generator gets to make

Both markups are handled, because they hide the same list in different syntax:

    RST     .. toctree::            MyST    ```{toctree}
               :maxdepth: 2                 :maxdepth: 2
                                            (blank)
               page-one                     page-one
               page-two                     page-two
                                            ```

The RST block ends at the first line that is neither blank nor indented past the
directive. The MyST block ends at its closing fence. Both are found by structure rather
than by pattern-matching entries, so an entry containing anything unusual is still
preserved rather than dropped.

Standard library only. Writes only the index it was given, and only when it changed.
"""

import os
import re
import sys

RST_DIRECTIVE = re.compile(r"^(\s*)\.\.\s+toctree::\s*$")
MYST_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})\{toctree\}\s*$")
OPTION = re.compile(r"^\s*:[A-Za-z][\w-]*:")


class Refused(Exception):
    """The index was left exactly as it was, and here is why."""


def _rst_span(lines, start):
    """Where the entry list of an RST toctree begins and ends.

    The directive owns every following line that is blank or indented past it. Options
    come first; entries are whatever indented lines follow them.
    """
    indent = len(RST_DIRECTIVE.match(lines[start]).group(1))
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            end += 1
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    # Trailing blank lines belong to whatever follows, not to the directive.
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start + 1, end


def _myst_span(lines, start):
    fence = MYST_OPEN.match(lines[start]).group(2)
    # A closing fence is at least as long as the opening one, and of the same character.
    closing = re.compile(r"^\s*%s{%d,}\s*$" % (re.escape(fence[0]), len(fence)))
    for position in range(start + 1, len(lines)):
        if closing.match(lines[position]):
            end = position
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            return start + 1, end
    raise Refused("the MyST toctree at line %d is never closed" % (start + 1))


def _blocks(lines):
    """Every toctree in the file, as (start, body_start, body_end, indent)."""
    found = []
    for position, line in enumerate(lines):
        if RST_DIRECTIVE.match(line):
            body_start, body_end = _rst_span(lines, position)
            indent = len(RST_DIRECTIVE.match(line).group(1)) + 3
            found.append((position, body_start, body_end, " " * indent))
        elif MYST_OPEN.match(line):
            body_start, body_end = _myst_span(lines, position)
            found.append((position, body_start, body_end, ""))
    return found


def wire(path, entries):
    """Add `entries` to the single toctree in `path`. Returns (changed, note)."""
    if not os.path.isfile(path):
        raise Refused("no such index: %s" % path)
    # Read without newline translation. Reading universally and writing "\n" would
    # convert a CRLF file line by line: the promise is that everything outside the entry
    # list survives byte for byte, and a whole-file diff on a Windows checkout breaks it
    # more thoroughly than any wrong entry would.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    ending = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    blocks = _blocks(lines)
    if not blocks:
        raise Refused(
            "%s has no toctree. Adding one means choosing where in the document it "
            "belongs, which is the author's decision; add the directive and rerun"
            % os.path.basename(path))
    if len(blocks) > 1:
        raise Refused(
            "%s has %d toctrees and nothing says which one these pages belong in; "
            "add them by hand" % (os.path.basename(path), len(blocks)))

    _, body_start, body_end, indent = blocks[0]
    body = lines[body_start:body_end]
    listed = set()
    for line in body:
        stripped = line.strip()
        if stripped and not OPTION.match(line):
            # A caption entry is `Title <target>`; the target is what matches.
            listed.add(stripped.split("<")[-1].rstrip(">").strip())

    missing = [entry for entry in entries if entry not in listed]
    if not missing:
        return False, "every page was already listed in %s" % os.path.basename(path)

    # Options must stay directly under the directive, so new entries go after the last
    # non-entry line rather than at the top of the body.
    insert = len(body)
    while insert > 0 and not body[insert - 1].strip():
        insert -= 1
    # A directive's options must be separated from its content by a blank line. Where
    # the toctree has options and no entries yet, the span ends at the last option, so
    # appending straight onto it produces `:maxdepth: 2` followed by a page name and a
    # directive that no longer parses. `body` is not empty in that case -- the options
    # are in it -- so emptiness is the wrong test; having no entry is the right one.
    entries_present = [line for line in body if line.strip() and not OPTION.match(line)]
    separator = [] if entries_present else [""]
    updated = (body[:insert] + separator
               + [indent + entry for entry in missing] + body[insert:])

    rebuilt = lines[:body_start] + updated + lines[body_end:]
    output = ending.join(rebuilt)
    if text.endswith(("\n", "\r")):
        output += ending
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(output)
    return True, "added %d page(s) to the toctree in %s: %s" % (
        len(missing), os.path.basename(path), ", ".join(missing))


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: wire_toctree.py <index> <page> [page ...]\n")
        return 2
    try:
        changed, note = wire(sys.argv[1], sys.argv[2:])
    except Refused as exc:
        sys.stderr.write("REFUSED  %s\n" % exc)
        return 1
    print(note)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        sys.stderr.write("INTERNAL  %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)

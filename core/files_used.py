"""List of the input files used by a run (confirmed: the report lists the exact files used).

GROOPS reads its files internally, so the list is built from the executed scripts: every 'inputfile...' element
of every program that is not disabled, with the variables replaced as GROOPS does for this run
({groopsDataDir}, {loopTime:%D} and {loopTime:%y%03O} for EVERY processed day (TU Graz daily loop, CHANGED
2026-10-11), other <global> variables), restricted to files that exist on disk.
Templates with per-satellite variables ({prn}, {station}, ...) are listed with all matching files.
Limitation (stated in the report): this shows what the scripts name and what exists, not a trace of every read.
"""
import glob
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from core import settings

_VAR = re.compile(r"\{([^{}:]+)(?::[^{}]*)?\}")


def _globals(root, overrides):
    g = {}
    gl = root.find("global")
    if gl is not None:
        for e in gl:                                     # GROOPS: global elements are named by attribute 'label'
            if e.text and e.text.strip():
                g[e.get("label", e.tag)] = e.text.strip()
    g.update(overrides)
    return g


def resolve(text, variables, day=settings.START):
    """Replace GROOPS variables for one day; unknown ones become '*' (glob)."""
    from datetime import date
    d = date.fromisoformat(day)
    t = text.replace("{loopTime:%D}", day).replace("{loopTime:%y%03O}", f"{d.year}{d.timetuple().tm_yday:03d}")
    for _ in range(5):                                   # nested variables
        new = _VAR.sub(lambda m: variables.get(m.group(1), "\0" + m.group(1) + "\0"), t)
        if new == t:
            break
        t = new
    return re.sub(r"\0[^\0]*\0", "*", t)


def _inputs(node, out):
    if node.get("disabled") == "1":
        return
    if node.tag.startswith("inputfile") and node.text and node.text.strip():
        out.append(node.text.strip())
    for c in node:
        _inputs(c, out)


def script_inputs(script, run_dir, overrides):
    """Existing input files named by the enabled programs of one executed script."""
    root = ET.parse(script).getroot()
    variables = _globals(root, overrides)
    names = []
    _inputs(root, names)
    found = set()
    for n in names:
        for day in settings.DAYS:                        # CHANGED 2026-10-11: files of every day
            p = resolve(n, variables, day)
            p = p if Path(p).is_absolute() else str(Path(run_dir) / p)
            hits = glob.glob(p) if "*" in p else ([p] if Path(p).exists() else [])
            for h in hits:
                if Path(h).is_file():
                    found.add(str(Path(h).resolve()))
    return sorted(found)


def describe(path):
    p = Path(path)
    return f"{p}  ({p.stat().st_size} bytes)" if p.is_file() else f"{p}  (missing)"

"""Final product (NEW 2026-10-12, user decision): the reduced-dynamic orbit without the first and last
settings.FINAL_TRIM_HOURS of the whole processed period (end effects).

Applied only after all calculations are done. GROOPS's own files in output/ stay unchanged (they are inputs of
later steps); the trimmed copies are written to <run folder>/final/<day>/. The epoch lines are copied unchanged
(no reformatting); the arc structure of the GROOPS file is kept; empty arcs and empty days are not written.
"""
from pathlib import Path

from core import settings

FINAL = "final"


def final_file(run_dir, day):
    return Path(run_dir) / FINAL / day / f"{settings.SATELLITE}_orbit_reducedDynamic_{day}.txt"


def _trim(src, dst, t0, t1):
    """Copy a GROOPS text instrument file keeping only epochs with t0 <= t < t1. Returns kept epochs."""
    lines = Path(src).read_text().splitlines()
    head, arcs, i = lines[:5], [], 5
    while i < len(lines) and lines[i].strip():
        n = int(lines[i])
        # CHANGED 2026-10-14 (user): 3 h trim disabled (original line kept below, commented out)
        # keep = [l for l in lines[i + 1:i + 1 + n] if t0 <= float(l.split()[0]) < t1]
        keep = lines[i + 1:i + 1 + n]  # CHANGED: keep all epochs
        if keep:
            arcs.append(keep)
        i += 1 + n
    kept = sum(len(a) for a in arcs)
    if kept:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(head + [x for a in arcs for x in [f"{len(a):11d}"] + a]) + "\n")
    return kept


def make_final(run_dir, rd_files):
    """rd_files: daily reduced-dynamic orbit files (output/). Returns (report lines, final files written)."""
    h = settings.FINAL_TRIM_HOURS
    t0, t1 = settings.TIME_START + h / 24, settings.TIME_END - h / 24
    lines = [f"[final] reduced-dynamic orbit without the first and last {h} h of {settings.START} .. {settings.END}"
             f" -> {Path(run_dir) / FINAL}"]
    out = []
    for day, f in zip(settings.DAYS, rd_files):
        dst = final_file(run_dir, day)
        n = _trim(f, dst, t0, t1)
        lines.append(f"[final] {day}: {n} epochs" + (f" ({dst})" if n else " (whole day removed, no file)"))
        if n:
            out.append(dst)
    return lines, out

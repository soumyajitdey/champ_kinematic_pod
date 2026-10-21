"""
Removes physically impossible code observations from a CHAMP RINEX 2 file (NEW 2026-10-18).

Reason: in the 2003-11-19..23 run, GROOPS 03 (kinematic PPP) failed on the days that contain satellite records
with C1/P1/P2 far outside the physical range (e.g. 7.1e7 m); the day without such records ran.

Rule: a satellite record at an epoch is blanked (all observables of that satellite at that epoch) when any present
C1, P1 or P2 value is outside [RANGE_MIN, RANGE_MAX] metres. Epoch lines and satellite lists are unchanged; blank
fields mean "missing" in RINEX. The limits are fixed by this package (not from a publication): GPS ranges seen
from CHAMP (about 400 km altitude) are about 2e7..2.6e7 m.
"""
from pathlib import Path

RANGE_MIN = 1.5e7                                   # m
RANGE_MAX = 4.5e7                                   # m
CODE_TYPES = ("C1", "P1", "P2")


def _epoch(line):
    """(flag, number of satellites/lines) of a RINEX 2 epoch line, or None if the line is not an epoch line."""
    try:
        int(line[1:3]); int(line[4:6]); int(line[7:9]); int(line[10:12]); int(line[13:15]); float(line[15:26])
        return int(line[28:29]), int(line[29:32])
    except (ValueError, IndexError):
        return None


def filter_rinex(path):
    """Filters the file in place. Returns the list of (epoch text, satellite, values) that were blanked."""
    path = Path(path)
    lines = path.read_text(errors="replace").split("\n")
    types, i = [], 0
    while i < len(lines) and "END OF HEADER" not in lines[i]:
        if lines[i][60:].strip() == "# / TYPES OF OBSERV":
            types += lines[i][6:60].split()
        i += 1
    i += 1
    idx = [types.index(t) for t in CODE_TYPES if t in types]
    if not idx:
        raise ValueError(f"{path}: none of {CODE_TYPES} in the observation types {types}")
    nl = (len(types) + 4) // 5                      # lines per satellite record
    removed = []
    while i < len(lines):
        e = _epoch(lines[i])
        if e is None:
            i += 1
            continue
        flag, ns = e
        first = i
        nsl = (ns + 11) // 12                       # epoch line + continuation lines with the satellite list
        sats = "".join(lines[first + k][32:68].ljust(36) if k == 0 else lines[first + k][32:68].ljust(36)
                       for k in range(nsl))
        i += nsl
        if flag > 1:                                # special event: ns header lines follow, no observations
            i += ns
            continue
        for k in range(ns):
            rec = lines[i:i + nl]
            vals = []
            for j in idx:
                row = rec[j // 5].ljust(80) if j // 5 < len(rec) else ""
                f = row[16 * (j % 5):16 * (j % 5) + 14].strip()
                if f:
                    vals.append(float(f))
            if any(not (RANGE_MIN < v < RANGE_MAX) for v in vals):
                removed.append((lines[first][:26].strip(), sats[3 * k:3 * k + 3].strip(),
                                " ".join(f"{v:.3f}" for v in vals)))
                for m in range(nl):
                    lines[i + m] = " " * 80
            i += nl
    if removed:
        path.write_text("\n".join(lines))
    return removed

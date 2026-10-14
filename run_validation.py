"""Validation of a finished run (NEW 2026-10-11, confirmed V1, V2): steps 9 and 10 only, no orbit processing.

  python3 run_validation.py --run-dir work/results/<run folder> [--groops-bin /path/to/groops]

  9  comparison of our kinematic and reduced-dynamic orbit with TU Graz's kinematic and reduced-dynamic orbits
     (reduced-dynamic = final product from <run folder>/final/, first and last 3 h of the period removed)
 10  SLR validation: measured minus computed laser range for all four orbits (core/slr.py)

Standalone: results go to a NEW folder <run folder>/validation_<YYYYmmdd_HHMMSS>/ (earlier results are kept),
with validation_report.txt. run_pipeline.py calls validate() at the end of a full run with <run folder>/validation/.
External data (TU Graz orbits, SLR normal points, SLR station files) are used only here, never in the processing.
"""
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from core import champ, download, final, groops_exe, settings, slr   # CHANGED 2026-10-12: final
from core import validate as validate_mod
from core.groops_io import arc_starts, read_orbit

import numpy as np


def set_period(run_dir):
    """Period of the run from its RUN_OK file (written by run_pipeline.py); otherwise core/settings.py."""
    info = dict(l.split("=", 1) for l in (Path(run_dir) / "RUN_OK").read_text().split() if "=" in l)
    if "start" in info and "end" in info:
        start, end = info["start"], info["end"]
    else:
        start, end = settings.START, settings.END
        print(f"[validation] RUN_OK has no period; using core/settings.py: {start} .. {end}")
    settings.START, settings.END = start, end
    settings.DAYS = [str(date.fromisoformat(start) + timedelta(k))
                     for k in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)]
    settings.TIME_START = (date.fromisoformat(start) - settings.MJD0).days
    settings.TIME_END = settings.TIME_START + len(settings.DAYS)


def orbit_sets(run_dir):
    """Our daily orbit files of the run: kinematic (script 03) and reduced-dynamic (script 05, if run)."""
    from core import files_used
    out = {}
    s03, s05 = Path(run_dir) / champ.ORDER[3], Path(run_dir) / champ.ORDER[5]
    templ = {"kinematic": champ.kinematic_outputs(s03.read_text())[0]}
    if s05.is_file():
        templ["reduced-dynamic"] = champ.rd_orbit_file(s05.read_text())
    for k, t in templ.items():
        files = [Path(run_dir) / files_used.resolve(t, {}, d) for d in settings.DAYS]
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            print(f"[validation] {k} orbit files missing, not validated: {missing}")
            continue
        out[k] = files
    if "kinematic" not in out:
        sys.exit("[validation] no kinematic orbit files in the run folder; nothing to validate")
    if "reduced-dynamic" in out:                                  # NEW 2026-10-12: validate the final product
        finals = [final.final_file(run_dir, d) for d in settings.DAYS]
        if not any(f.is_file() for f in finals):                  # run made before 2026-10-12: create final/
            for l in final.make_final(run_dir, out["reduced-dynamic"])[0]:
                print(l)
        out["reduced-dynamic"] = [f for f in finals if f.is_file()]   # trimmed orbit from final/
    return out


def validate(run_dir, out_dir, exe, data_dir):
    """Steps 9 and 10. Returns (report lines, external files used, {check: count})."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    sets = orbit_sets(run_dir)
    print("[9] comparison with TU Graz orbits")
    lines, files, counts = validate_mod.compare(sets, out_dir)
    lines = ["[9] comparison with TU Graz orbits"] + lines
    lines += [f"[check 9] compared epochs, {label}: {n}" for label, n in counts.items()]
    # SLR validation (step 10) switched off 2026-10-11 (user: too few normal points, 10-20 per day).
    # To switch it on again, remove the "# " in front of the next 9 lines and delete the 2 lines after them.
    # arcs = np.array([])
    # if "reduced-dynamic" in sets:
    #     arcs = np.concatenate([np.r_[read_orbit(f)[0][:1], arc_starts(f)] for f in sets["reduced-dynamic"]])
    # print("[10] SLR validation")
    # ours = {("reducedDynamic" if k == "reduced-dynamic" else k): v for k, v in sets.items()}
    # slr_lines, slr_files, n = slr.validate(run_dir, out_dir, exe, data_dir, ours, arcs)
    # counts["SLR normal points common to all orbits"] = n
    # lines += slr_lines + [f"plots: {out_dir}"]
    # return lines, sorted(set(files) | set(slr_files)), counts
    lines += [f"plots: {out_dir}"]                                       # CHANGED 2026-10-11: no SLR
    return lines, sorted(set(files)), counts                              # CHANGED 2026-10-11: no SLR


def main():
    ap = argparse.ArgumentParser(description="Validation of a finished CHAMP run (TU Graz comparison + SLR)")
    ap.add_argument("--run-dir", required=True, help="folder work/results/<run> of a finished run")
    ap.add_argument("--groops-bin", default=None)
    a = ap.parse_args()
    run_dir = Path(a.run_dir).resolve()
    if not (run_dir / "RUN_OK").is_file():
        sys.exit(f"[validation] {run_dir} has no RUN_OK file (run not finished)")
    set_period(run_dir)
    exe = groops_exe.get_groops(a.groops_bin)
    data_dir = download.get_groops_data(champ.template_dirs(), champ.EXTRA_DATA)
    out_dir = run_dir / f"validation_{time.strftime('%Y%m%d_%H%M%S')}"
    lines, files, counts = validate(run_dir, out_dir, exe, data_dir)
    report = [f"Validation of {run_dir}", f"period {settings.START} .. {settings.END}", ""] + lines
    report += ["", "=== external files used by the validation (never by the processing) ==="] + ["  " + f for f in files]
    (out_dir / "validation_report.txt").write_text("\n".join(report) + "\n")
    print("\n".join(l for l in lines if l.startswith("[check")))
    print(f"\n[done] {out_dir / 'validation_report.txt'}")
    if any(n == 0 for n in counts.values()):
        sys.exit("[validation] at least one check is zero (see validation_report.txt)")


if __name__ == "__main__":
    main()

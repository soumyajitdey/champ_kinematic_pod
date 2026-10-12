"""CHAMP orbit from its own GPS receiver data only: kinematic PPP, then reduced-dynamic POD, with GROOPS
(pipeline confirmed 2026-10-10; reduced-dynamic POD added 2026-10-11, confirmed: version 2, one process).

  python3 run_pipeline.py                         (a priori orbit option: polynomial, the default)
  python3 run_pipeline.py --start-orbit dynamic
  options: --products repro3|final|ultra (default repro3), --groops-bin /path/to/groops

No CHAMP RSO and no other external CHAMP orbit is downloaded or read at any step. TU Graz's published CHAMP
orbits and the SLR data are downloaded only for the validation in steps 9-10 (never used in the processing).

Execution order (confirmed item A):
  1 check inputs: by-hand files missing -> stop and list them; then download what the script can download
  2 RTKLIB: rough CHAMP position per epoch from the RINEX pseudoranges (core/spp.py)
  3 GROOPS 01: GPS products                    (TU Graz script, unchanged for repro3)
  4 GROOPS 02: CHAMP RINEX + attitude + rough positions
  5 GROOPS 02b: a priori orbit (polynomial or dynamic) + same epochs as the attitude
  6 GROOPS 03: kinematic PPP                   (TU Graz script, wavelengthFactor 1)
  7 GROOPS 04: force-model orbit fitted to the kinematic positions (TU Graz reduced-dynamic 03groopsVariational.xml)
               = a priori orbit of the reduced-dynamic POD (NEW 2026-10-11)
  8 GROOPS 05: reduced-dynamic POD: force-model orbit + 20-min stochastic pulses estimated from the CHAMP GPS
               pseudoranges and carrier phases (TU Graz reduced-dynamic 04groopsGnssProcessing.xml, NEW 2026-10-11)
  Steps 3-8 run TU Graz's daily loop (CHANGED 2026-10-11): each day uses only its own files, incl. its own GPS
  signal-bias file (one bias file for several days gave wrong integer ambiguities on 2010-05-01).
  9 comparison of the kinematic AND the reduced-dynamic orbit with TU Graz's kinematic and reduced-dynamic orbits
 10 SLR validation: measured minus computed laser range for our and TU Graz's orbits (NEW 2026-10-11, core/slr.py)
    Steps 9-10 = run_validation.py, which can also be run alone on a finished run folder.
 11 report: settings, check numbers, comparison, exact files used, limitations
Each run: work/results/CHAMP_<start-orbit>_<products>_<YYYYmmdd_HHMMSS>/ (nothing is overwritten).
"""
import argparse
import sys
import time
from pathlib import Path

from core import champ, download, files_used, gnss_products, groops_exe, run_groops, settings, spp
from core.groops_io import read_orbit, read_instrument

LIMITATIONS = """Known limitations (accepted 2026-10-10, tester review):
 1. The TU Graz comparison is not independent: TU Graz computed its CHAMP orbits with GROOPS, probably with the
    same TUG repro3 GPS products. Agreement shows consistency, not accuracy (independent check: SLR).
 2. The dynamic a priori option and the reduced-dynamic POD (steps 7-8) are new and untested on real data.
 3. The TU Graz scenario zip files carry no version number (checksums listed above).
 4. repro3 products are not available in near real time; ultra-rapid has 15-min clocks and no biases (float ambiguities).
 5. CHAMP hardware (dual-frequency geodetic receiver, 10 s, star camera) differs from the mission hardware.
 6. Reduced-dynamic POD: GPS observations are used only at the receiver epochs kept by the kinematic run (epochs
    without an RTKLIB rough position were removed in step 5) and inside the arcs of the fitted orbit (no
    kinematic positions for more than 30 s -> new arc). Arcs and carrier-phase ambiguities restart at midnight
    (TU Graz daily loop).
 7. The code was written without access to real CHAMP data; the per-step checks show where a run stops.
 8. 'Files used' = files named by the enabled programs and present on disk, not a trace of every read.
 9. RTKLIB behaviour was trace-checked on version 2.4.3 b34; the installed version may differ.
10. Only 2 quiet solar-minimum days.
11. The cm-level target has no published source; the RMS vs TU Graz contains TU Graz's own errors too.
12. SLR validation (NEW 2026-10-11): CHAMP was tracked in short passes by few stations, so two days give few normal
    points; the retroreflector position is the nominal design value (250 mm from the centre of mass to nadir); ILRS
    station range/time biases are not applied (determined with passive satellites only), so station biases remain
    in the residuals; SLR measures only the line-of-sight component of the orbit error."""


def stop(msg):
    sys.exit(f"\n[STOP] {msg}")


def step1_inputs(products):
    """Create folders; stop with a list of every missing by-hand file; then download the rest."""
    for d in (settings.INPUTS / "brdc", settings.REPRO3_LOCAL, settings.INPUTS / "champ"):
        d.mkdir(parents=True, exist_ok=True)
    missing = champ.missing_brdc() + gnss_products.missing_by_hand(products, settings.DAYS)
    import shutil
    if not shutil.which("rnx2rtkp"):
        missing.append("RTKLIB program rnx2rtkp (install once: sudo apt install rtklib)")
    if missing:
        stop("files to provide by hand are missing. Copy them to exactly these paths, then run again:\n  - "
             + "\n  - ".join(missing))
    print("[1] by-hand files present; downloading the rest (existing files are kept)")
    champ_dir = champ.get_champ_inputs()
    igs_dir = gnss_products.get_products(products, settings.DAYS)
    tdirs = champ.template_dirs()
    data_dir = download.get_groops_data(tdirs, champ.EXTRA_DATA)
    return champ_dir, igs_dir, data_dir


def step2_rtklib(run_dir, products):
    """Rough positions per day into <run>/champ/SPP_<day>.sp3. Returns report lines."""
    sp3 = [str(f) for f in gnss_products.sp3_files(products, settings.DAYS)]
    lines = []
    for day in settings.DAYS:
        from datetime import date, timedelta
        prev, nxt = (str(date.fromisoformat(day) + timedelta(days=k)) for k in (-1, 1))
        nav = [f for f in (champ.brdc(prev), champ.brdc(day), champ.brdc(nxt)) if f is not None]
        rnx = run_dir / "champ" / f"CH-OG-1-SST_{day}.rnx"
        n_ok, n = spp.make_spp_sp3(rnx, sp3, nav, run_dir / "champ" / f"SPP_{day}.sp3")
        lines.append(f"[check 2] {day}: RTKLIB positions accepted {n_ok} of {n} epochs")
        print(lines[-1])
        if n_ok == 0:
            stop(f"no accepted RTKLIB position on {day}")
        RTKLIB_FILES.extend([str(rnx)] + sp3 + [str(f) for f in nav])
    return lines


RTKLIB_FILES = []


def count_epochs(path):
    try:
        return read_instrument(path)[1].shape[0]
    except Exception as e:
        stop(f"cannot read {path}: {e}")


def check_apriori(run_dir, report, no, template, what):
    """Per-day number of epochs in the text copy of an a priori orbit; stop if zero."""
    total = 0
    for day in settings.DAYS:
        n = count_epochs(run_dir / files_used.resolve(template, {}, day))
        total += n
        report.append(f"[check {no}] {day}: epochs with {what}: {n}")
        print(report[-1])
        if n == 0:
            stop(f"no epoch with {what} on {day}; see the log files in {run_dir / 'log'}")
    report.append(f"[check {no}] all days: {total}")


def check_orbit(run_dir, report, no, template, what):
    """Per-day number of epochs in an orbit result file; stop if missing or zero. Returns the daily files."""
    files, total = [], 0
    for day in settings.DAYS:
        f = run_dir / files_used.resolve(template, {}, day)
        if not f.is_file():
            stop(f"{what}: file not found: {f}; see the log files in {run_dir / 'log'}")
        n = len(read_orbit(f)[0])
        total += n
        report.append(f"[check {no}] {day}: {what}: {n}  ({f})")
        print(report[-1])
        if n == 0:
            stop(f"no {what} on {day}")
        files.append(f)
    report.append(f"[check {no}] all days: {total}")
    return files


def main():
    ap = argparse.ArgumentParser(description="CHAMP GPS-only kinematic PPP + reduced-dynamic POD (GROOPS)")
    ap.add_argument("--start-orbit", default="polynomial", choices=settings.START_ORBITS,   # CHANGED 2026-10-11:
                    help="a priori orbit from the RTKLIB rough positions: polynomial (default) or dynamic")  # default
    ap.add_argument("--products", choices=settings.PRODUCTS, default="repro3")
    ap.add_argument("--groops-bin", default=None)
    a = ap.parse_args()

    # ---------- step 1 ----------
    champ_dir, igs_dir, data_dir = step1_inputs(a.products)
    exe = groops_exe.get_groops(a.groops_bin)
    scripts, (apriori, star, kin_orbit, rd_orbit) = champ.scripts(a.start_orbit, a.products)

    results = settings.RESULTS / f"{settings.NAME}_{a.start_orbit}_{a.products}_{time.strftime('%Y%m%d_%H%M%S')}"
    files = dict(scripts)
    files.update({"02observationTypes.champ.txt": champ.OBS_TYPES, "champ": champ_dir, "igs": igs_dir})
    run_dir = run_groops.prepare(results, files)
    (run_dir / "checks").mkdir()
    glob_ = {"timeStart": str(settings.TIME_START), "timeEnd": str(settings.TIME_END)}
    report = [f"CHAMP GPS-only kinematic PPP + reduced-dynamic POD, {settings.START} .. {settings.END}",
              "processing: TU Graz daily loop; every day uses only its own input files incl. its own GPS signal biases",
              f"a priori orbit option: {a.start_orbit}", f"GPS products: {a.products}",
              f"GROOPS executable: {exe} (release {settings.GROOPS_TAG} expected)",
              f"GROOPS data: {data_dir}", f"run folder: {run_dir}", "CHAMP RSO: not used (not downloaded, not read)",
              "", "TU Graz scenario zip files (no version number; identified by download date and SHA-256):"]
    for n in settings.SCENARIOS:
        z, when, sha = download.scenario_zip_info(n)
        report.append(f"  {z}\n    downloaded {when}, SHA-256 {sha}")
    report.append("")

    # ---------- step 2 ----------
    print("[2] RTKLIB rough positions")
    report += step2_rtklib(run_dir, a.products)

    # ---------- steps 3-8 ----------
    order = champ.ORDER
    labels = dict(zip(order, ["[3] GROOPS 01 GPS products", "[4] GROOPS 02 CHAMP conversion",
                              f"[5] GROOPS 02b a priori orbit ({a.start_orbit})", "[6] GROOPS 03 kinematic PPP",
                              "[7] GROOPS 04 force-model orbit fitted to the kinematic positions",
                              "[8] GROOPS 05 reduced-dynamic POD"]))
    orbit_sets = {}
    for s in order:
        print(labels[s])
        run_groops.run_scripts(run_dir, [s], data_dir, exe, glob_)
        if s == order[2]:                                        # CHANGED 2026-10-11: per day (TU Graz daily loop)
            check_apriori(run_dir, report, 5, champ.CHECK_APRIORI, "a priori position (after TU Graz synchronization)")
        elif s == order[3]:
            orbit_sets["kinematic"] = check_orbit(run_dir, report, 6, kin_orbit, "kinematic positions")
        elif s == order[4]:                                      # NEW 2026-10-11
            check_apriori(run_dir, report, 7, champ.CHECK_APRIORI_RD,
                          "reduced-dynamic a priori position (fitted orbit, after TU Graz synchronization)")
        elif s == order[5]:                                      # NEW 2026-10-11
            orbit_sets["reduced-dynamic"] = check_orbit(run_dir, report, 8, rd_orbit, "reduced-dynamic positions")
    (run_dir / "RUN_OK").write_text(f"start-orbit={a.start_orbit}\nproducts={a.products}\n"
                                    f"start={settings.START}\nend={settings.END}\n")      # CHANGED 2026-10-11: period

    # ---------- steps 9-10 (run_validation.py, NEW 2026-10-11) ----------
    lines, ref_files, counts = run_validation.validate(run_dir, run_dir / "validation", exe, data_dir)
    report += [""] + lines

    # ---------- step 11 ----------
    report += ["", "=== files used ===", "Inputs from outside the run (copies in the run folder come from "
               f"{champ_dir} and {igs_dir}):"]
    external, internal = set(), set()
    for s in order:
        for f in files_used.script_inputs(run_dir / s, run_dir, {"groopsDataDir": str(Path(data_dir).resolve()), **glob_}):
            rel = Path(f).resolve()
            in_run = str(rel).startswith(str(run_dir.resolve()))
            parts = rel.relative_to(run_dir.resolve()).parts if in_run else ()
            produced = in_run and (parts[0] in ("data", "checks", "output") or rel.name.startswith("SPP_"))
            (internal if produced else external).add(f"{s}: {files_used.describe(f)}")
    for f in sorted(set(RTKLIB_FILES)):
        external.add(f"RTKLIB: {files_used.describe(f)}")
    for f in sorted(set(ref_files)):
        external.add(f"validation only: {files_used.describe(f)}")
    report += ["  " + x for x in sorted(external)]
    report += ["Intermediate files produced in this run (RTKLIB SPP_*.sp3, GROOPS data/) and read by later steps:"] + ["  " + x for x in sorted(internal)]
    report += ["", LIMITATIONS]
    (run_dir / "report.txt").write_text("\n".join(report) + "\n")
    print("\n".join(l for l in report if l.startswith("[check") or l[:10] in settings.DAYS or l.startswith("all days")
                    or "===" in l))
    print(f"\n[done] report: {run_dir / 'report.txt'}")
    if not counts or any(n == 0 for n in counts.values()):
        stop("at least one validation check is zero (see report.txt); the orbits themselves are in "
             f"{run_dir / 'output'}")


import run_validation  # noqa: E402  (NEW 2026-10-11: steps 9-10)

if __name__ == "__main__":
    main()

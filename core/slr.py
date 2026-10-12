"""Step 10: SLR validation (NEW 2026-10-11, confirmed items 4-16, A, B). VALIDATION ONLY.

Satellite laser ranging (SLR) normal points are used ONLY here, after all orbits are final. No processing step
(scripts 01-05) reads any SLR file; check_isolation() stops the run if one does.

What is computed (GROOPS SlrProcessing, nothing estimated):
  residual = measured one-way laser range - range computed from the orbit       [one value per normal point]
  The computed range contains: orbit interpolated to the SLR epoch (degree-7 polynomial through the 8 nearest orbit
  points, GROOPS default; no value if the orbit has a gap there), retroreflector offset rotated with the CHAMP
  attitude, light travel time, station coordinates (SLRF2020, centre-of-mass frame), station tides and loading
  (TU Graz's settings from their GNSS PPP scenario, unchanged), Mendes-Pavlis troposphere with the meteorological
  data in the normal points, relativistic (Shapiro) delay. No ILRS station range/time biases (GROOPS documentation:
  determined with passive satellites, not suitable for active ones; item A).
Orbits checked (item 14): our kinematic and reduced-dynamic orbit, TU Graz's kinematic and reduced-dynamic orbit,
  all against the same normal points.
Statistics: (a) all residuals, (b) screened as in Strugarek et al. 2022, GPS Solut 26:104: |residual| > 15 cm
  removed, then station-days with a standard deviation > 5 cm removed. Both on the normal points common to all orbits.
Data: ILRS EDC CSTG normal points (days START-1 .. END+1, so that passes near midnight are complete), GROOPS
  converters Cstg2NormalPoints (UTC -> GPS time, two-way -> one-way) and PlatformCreate (CHAMP retroreflector).
"""
import copy
import gzip
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core import champ, download, run_groops, settings
from core.groops_io import read_instrument, read_orbit

D = "{loopTime:%D}"
SAT = settings.SATELLITE
STATION_TAGS = ["loadingDisplacement", "tidalDisplacement", "ephemerides",            # TU Graz PPP: stationNetwork
                "inputfileDeformationLoadLoveNumber", "inputfilePotentialLoadLoveNumber"]


def check_isolation(run_dir):
    """Stop if any processing script (01-05) refers to SLR data (SLR is for validation only)."""
    bad = [s for s in champ.ORDER if (Path(run_dir) / s).is_file()
           and re.search(r"slr/|normalPoints|SlrProcessing|Cstg2NormalPoints", (Path(run_dir) / s).read_text())]
    if bad:
        sys.exit(f"[SLR] processing scripts refer to SLR data: {bad}. SLR is for validation only. Stopped.")


# ------------------------------------------------------------------------------------------------ inputs

def normal_point_files(days):
    """Download the EDC daily CSTG files of days-1 .. days+1. Returns (files, list of messages)."""
    d0, d1 = date.fromisoformat(days[0]) - timedelta(1), date.fromisoformat(days[-1]) + timedelta(1)
    files, notes = [], []
    for k in range((d1 - d0).days + 1):
        d = d0 + timedelta(k)
        url = settings.SLR_NP_URL.format(y=d.year, ymd=d.strftime("%Y%m%d"))
        try:
            files.append(download.fetch_url([url], settings.DOWNLOADS / "slr" / Path(url).name))
        except SystemExit as e:
            notes.append(f"no normal point file for {d} ({url}): {e}")
    return files, notes


def tug_station_settings():
    """TU Graz's station tide/loading settings: the elements STATION_TAGS of stationNetwork in their GNSS PPP
    scenario script, deep-copied unchanged, plus the global variables they use. Returns (script, elements, globals)."""
    root = download.get_scenario("gnssPPP")
    for xml in sorted(Path(root).rglob("*.xml")):
        try:
            r = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        sn = next(r.iter("stationNetwork"), None)
        if sn is None:
            continue
        elems = [copy.deepcopy(sn.find(t)) for t in STATION_TAGS if sn.find(t) is not None]
        used = set()
        for e in elems:
            for x in e.iter():
                if x.get("link"):
                    used.add(x.get("link"))
                used |= set(re.findall(r"\{([A-Za-z]\w*)\}", x.text or ""))
        gl = r.find("global")
        glob = [copy.deepcopy(g) for g in (gl if gl is not None else [])
                if g.get("label") in used and g.get("label") not in ("groopsDataDir", "timeStart", "timeEnd")]
        return xml, elems, glob
    sys.exit(f"[SLR] no stationNetwork found in the TU Graz GNSS PPP scenario ({root}). Stopped.")


def write_orbit_txt(path, t, pos, vel):
    """GROOPS instrument text file (ORBIT; layout as written by GROOPS 2025-11-15). Format conversion only."""
    vel = np.zeros_like(pos) if vel is None else vel
    head = ["groops instrument version=20200123", "# ORBIT", f"{-6:11d}{1:11d}",
            "# Time [MJD]  data0-2: pos x y z [m]  data3-5: vel x y z [m/s]  data6-8: acc x y z [m/s^2]",
            "# " + "=" * 40, f"{len(t):11d}"]
    rows = [f" {a:.18f} " + " ".join(f"{x:.18e}" for x in np.r_[p, v, 0.0, 0.0, 0.0]) for a, p, v in zip(t, pos, vel)]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(head + rows) + "\n")


def tug_orbit(kind, day, dest):
    """TU Graz published orbit of one day as a GROOPS-readable file (validation only). Returns dest or None."""
    from core import validate
    ref = validate.load_reference(kind, day)
    if ref is None:
        return None
    t, pos, vel, f = ref
    text = gzip.open(f, "rt").read() if str(f).endswith(".gz") else Path(f).read_text()
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    if text.startswith("groops instrument"):
        Path(dest).write_text(text)                      # already GROOPS format: decompressed copy
    else:
        write_orbit_txt(dest, t, pos, vel)
    return dest


# ------------------------------------------------------------------------------------------------ GROOPS scripts

def _e(tag, text=None, **attr):
    x = ET.Element(tag, attr)
    if text is not None:
        x.text = str(text)
    return x


def _sub(parent, tag, text=None):
    x = ET.SubElement(parent, tag)
    if text is not None:
        x.text = str(text)
    return x


def _prog(child, comment=None):
    p = ET.Element("program", {"comment": comment} if comment else {})
    p.append(child)
    return p


def _root(extra_globals=()):
    root = ET.Element("groops")
    g = _sub(root, "global")
    g.append(_e("time", settings.TIME_START, label="timeStart"))
    g.append(_e("time", settings.TIME_END, label="timeEnd"))
    g.append(_e("filename", "/groops/data", label="groopsDataDir"))
    for x in extra_globals:
        g.append(copy.deepcopy(x))
    return root


def script_normal_points(slr, cstg_files):
    """Script a: CHAMP platform file (retroreflector) and CSTG -> GROOPS normal points + meteorological data."""
    root = _root()
    root.append(_prog(_e("FileCreateDirectories"), f"{slr}/np/raw"))
    root[-1][0].append(_e("directory", f"{slr}/np/raw"))
    pc = _e("PlatformCreate")
    _sub(pc, "outputfilePlatform", f"{slr}/satelliteInfo.{SAT}.xml")
    _sub(pc, "markerName", SAT)
    eq = _sub(_sub(pc, "equipment"), "laserRetroReflector")
    _sub(eq, "name", f"{settings.NAME}-LRR")
    for c, v in zip("XYZ", settings.SLR_LRR):
        _sub(eq, f"position{c}", v)
    _sub(eq, "range", 0)
    eq = _sub(_sub(pc, "equipment"), "satelliteIdentifier")
    _sub(eq, "name", SAT)
    for k in ("cospar", "norad", "sic"):
        _sub(eq, k, settings.SLR_IDS[k])
    root.append(_prog(pc, "CHAMP retroreflector (nominal position, item 6)"))
    for f in cstg_files:
        tag = Path(f).name.split(".")[-1]
        c = _e("Cstg2NormalPoints")
        _sub(c, "outputfileNormalPoints", f"{slr}/np/raw/np_{tag}_{{station}}.dat")
        _sub(c, "outputfileMeteorological", f"{slr}/np/raw/met_{tag}_{{station}}.dat")
        _sub(c, "inputfileSlrData", str(Path(f).resolve()))
        root.append(_prog(c, f"normal points {Path(f).name}"))
    return champ._xml(root)


def _concat(out, inputs):
    c = _e("InstrumentConcatenate")
    _sub(c, "outputfile", out)
    for i in inputs:
        _sub(c, "inputfile", i)
    _sub(c, "sort", 1)
    _sub(_sub(_sub(c, "removeDuplicates"), "keepFirst"), "margin", "1e-5")
    return _prog(c, out + " (all files, sorted, duplicates removed)")


def script_processing(slr, raw, stations, orbits, star, star_resample, earth_rotation, station_elems, extra_globals):
    """Script b: per station one sorted normal point and meteorological file; then TU Graz's daily loop: for every
    orbit, attitude resampled to the orbit epochs (TU Graz's own resampling program of script 02) and synchronized,
    then GROOPS SlrProcessing (nothing estimated) -> residual files."""
    root = _root(extra_globals)
    for s in stations:
        for kind, name in (("np", f"normalPoints_{SAT}"), ("met", "meteorological")):
            root.append(_concat(f"{slr}/np/{name}_{s}.dat", [f for f in raw if Path(f).name.startswith(f"{kind}_")
                                                              and Path(f).stem.endswith(f"_{s}")]))
    lp = _e("LoopPrograms")
    ti = _sub(_sub(lp, "loop"), "timeIntervals")
    us = _sub(_sub(ti, "timeIntervals"), "uniformSampling")
    us.append(_e("timeStart", link="timeStart"))
    us.append(_e("timeEnd", link="timeEnd"))
    _sub(us, "sampling", 1)
    _sub(ti, "variableLoopTimeStart", "loopTime")
    _sub(ti, "variableLoopTimeEnd", "loopTimeEnd")
    _sub(lp, "continueAfterError", 0)
    root.append(_prog(lp, "daily (TU Graz daily loop)"))
    for k, orbit_in in orbits.items():
        o, a = f"{slr}/{k}/orbit_{D}.dat", f"{slr}/{k}/starCamera_{D}.dat"
        lp.append(_prog(_e("FileCreateDirectories"), f"{slr}/{k}"))
        lp[-1][0].append(_e("directory", f"{slr}/{k}"))
        r = copy.deepcopy(star_resample)                         # TU Graz's attitude resampling, other epochs
        r.attrib.pop("disabled", None)
        r.set("comment", f"{a} (attitude -> epochs of the {k} orbit, TU Graz's resampling of script 02)")
        ir = r.find("InstrumentResample")
        ir.find("outputfileInstrument").text = a
        ir.find("inputfileInstrument").text = star
        ir.find("timeSeries/instrument/inputfileInstrument").text = orbit_in
        lp.append(r)
        sy = _e("InstrumentSynchronize")
        for out, inp in ((o, orbit_in), (a, a)):
            d = _sub(sy, "data")
            _sub(d, "outputfileInstrument", out)
            _sub(d, "inputfileInstrument", inp)
        _sub(sy, "margin", "1e-5")
        us = _sub(_sub(sy, "timeIntervals"), "uniformSampling")
        _sub(us, "timeStart", "loopTime")
        _sub(us, "timeEnd", "loopTimeEnd")
        _sub(us, "sampling", "loopTimeEnd-loopTime")
        lp.append(_prog(sy, f"{o}: orbit and attitude with identical epochs (required by GROOPS)"))

        sp = _e("SlrProcessing")
        us = _sub(_sub(sp, "timeSeries"), "uniformSampling")
        _sub(us, "timeStart", "loopTime")
        _sub(us, "timeEnd", "loopTimeEnd")
        _sub(us, "sampling", "10/1440")                          # GROOPS documentation: about 10 minutes
        sa = _sub(_sub(sp, "satellite"), "satellites")
        _sub(sa, "inputfileSatelliteList", f"{slr}/satelliteList.txt")
        _sub(sa, "inputfileSatelliteInfo", f"{slr}/satelliteInfo.{{satellite}}.xml")
        _sub(sa, "inputfileOrbit", o)
        _sub(sa, "inputfileAttitude", a)
        _sub(sa, "interpolationDegree", settings.SLR_INTERPOLATION_DEGREE)
        st = _sub(_sub(sp, "station"), "stations")
        _sub(st, "inputfileStationList", f"{slr}/stationList.txt")
        _sub(st, "inputfileStationInfo", "{groopsDataDir}/slr/stations/stationInfo/stationInfo.{station}.xml")
        _sub(st, "inputfileStationPosition",
             "{groopsDataDir}/slr/stations/position/slrf2020_CM/stationPosition.{station}.dat")
        _sub(st, "disableStationWithoutPosition", 1)              # no SLRF2020 coordinates -> station not used
        _sub(st, "inputfileObservations", f"{slr}/np/normalPoints_{{satellite}}_{{station}}.dat")
        _sub(st, "accuracy", "if(abs(residual)>30, NAN, accuracy)")   # GROOPS default (gross errors > 30 m)
        for e in station_elems:                                  # TU Graz, unchanged
            st.append(copy.deepcopy(e))
        _sub(st, "elevationCutOff", settings.SLR_ELEVATION_CUTOFF)
        sp.append(copy.deepcopy(earth_rotation))                 # same as the orbit processing (TU Graz)
        tr = _sub(_sub(sp, "parametrization"), "troposphere")
        _sub(tr, "name", "parameter.troposphere")
        _sub(_sub(tr, "selectStations"), "all")
        _sub(_sub(_sub(tr, "troposphere"), "mendesAndPavlis"), "inputfileStationMeteorology",
             f"{slr}/np/meteorological_{{station}}.dat")
        es = _sub(_sub(sp, "processingStep"), "estimate")         # no parameters: residuals only
        for k2, v in (("computeResiduals", 1), ("adjustSigma0", 0), ("computeWeights", 0), ("maxIterationCount", 1)):
            _sub(es, k2, v)
        wr = _sub(_sub(sp, "processingStep"), "writeResiduals")
        _sub(_sub(wr, "selectStations"), "all")
        _sub(_sub(wr, "selectSatellites"), "all")
        _sub(wr, "outputfileResiduals", f"{slr}/{k}/residuals_{D}.{{station}}.{{satellite}}.txt")
        lp.append(_prog(sp, f"SLR residuals, {k} orbit"))
    return champ._xml(root)


def _station_tidy(e):
    """Order of the station elements as read by GROOPS (slrStationGeneratorStations.cpp)."""
    return STATION_TAGS.index(e.tag)


# ------------------------------------------------------------------------------------------------ statistics

def _residuals(slr_dir, k, days):
    """{(station, ms): (t, residual [m], elevation [deg])} of one orbit; a normal point counts on its own day."""
    out = {}
    for i, day in enumerate(days):
        for f in sorted((slr_dir / k).glob(f"residuals_{day}.*.{SAT}.txt")):
            station = f.name.split(".")[1]
            _, d = read_instrument(f)
            if d.shape[1] < 8:
                continue
            t0 = settings.TIME_START + i
            for row in d:
                if t0 <= row[0] < t0 + 1:
                    out[(station, int(round(row[0] * 86400e3)))] = (row[0], row[1], np.degrees(row[7]))
    return out


def _screen(res):
    """Strugarek et al. 2022: |residual| > 15 cm removed; then station-days with std > 5 cm removed."""
    keep = {k: v for k, v in res.items() if abs(v[1]) <= settings.SLR_SCREEN_RESIDUAL}
    groups = {}
    for (s, ms), v in keep.items():
        groups.setdefault((s, int(v[0])), []).append((s, ms))
    for keys in groups.values():
        if len(keys) > 1 and np.std([keep[k][1] for k in keys]) > settings.SLR_SCREEN_STATION_STD:
            for k in keys:
                keep.pop(k)
    return keep


def _stats(x):
    x = np.asarray(x) * 100
    return f"{len(x):6d} {x.mean():8.2f} {x.std():8.2f} {np.sqrt((x**2).mean()):8.2f}" if len(x) else f"{0:6d}"


def statistics(slr_dir, labels, days, arcs, out_png):
    """Report lines, number of common normal points; plot of the residuals."""
    res = {k: _residuals(slr_dir, k, days) for k in labels}
    common = set.intersection(*[set(r) for r in res.values()]) if res else set()
    scr = {k: _screen(r) for k, r in res.items()}
    common_s = set.intersection(*[set(r) for r in scr.values()]) if scr else set()
    lines = ["", "=== SLR validation: measured minus computed one-way range [cm] ===",
             "normal points used per orbit (all): " + ", ".join(f"{labels[k]} {len(r)}" for k, r in res.items()),
             f"(a) all residuals, normal points common to all orbits: {len(common)}",
             f"{'orbit':38} {'N':>6} {'mean':>8} {'std':>8} {'RMS':>8}"]
    lines += [f"{labels[k]:38} " + _stats([res[k][c][1] for c in common]) for k in labels]
    lines += [f"(b) screened (Strugarek et al. 2022: |res| > {settings.SLR_SCREEN_RESIDUAL*100:.0f} cm removed, then "
              f"station-days with std > {settings.SLR_SCREEN_STATION_STD*100:.0f} cm removed), common to all orbits: "
              f"{len(common_s)}", f"{'orbit':38} {'N':>6} {'mean':>8} {'std':>8} {'RMS':>8}"]
    lines += [f"{labels[k]:38} " + _stats([scr[k][c][1] for c in common_s]) for k in labels]
    stations = sorted({c[0] for c in common_s})
    if stations:
        short = {"kinematic": "our kinematic", "reducedDynamic": "our red.-dyn.", "tugKinematic": "TUG kinematic",
                 "tugReducedDynamic": "TUG red.-dyn."}
        lines += ["(b) per station: N, RMS [cm]",
                  f"{'station':8} {'N':>5} " + " ".join(f"{short[k]:>14}" for k in labels)]
        for s in stations:
            cs = [c for c in common_s if c[0] == s]
            lines.append(f"{s:8} {len(cs):5d} " + " ".join(
                f"{np.sqrt(np.mean(np.square([scr[k][c][1] for c in cs]))) * 100:14.2f}" for k in labels))
    _plot(res, scr, common, labels, arcs, out_png)
    return lines, len(common)


def _plot(res, scr, common, labels, arcs, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from core.validate import ARC, GRID, INK, LINE, MUTED
    if not common:
        return
    fig, axes = plt.subplots(len(labels), 1, figsize=(10, 2.2 * len(labels) + 1), sharex=True, squeeze=False)
    lim = 2 * settings.SLR_SCREEN_RESIDUAL * 100
    for ax, k in zip(axes[:, 0], labels):
        c = sorted(common, key=lambda x: res[k][x][0])
        h = np.array([(res[k][x][0] - settings.TIME_START) * 24 for x in c])
        r = np.array([res[k][x][1] * 100 for x in c])
        ok = np.array([x in scr[k] for x in c])
        ax.plot(h[~ok], np.clip(r[~ok], -lim, lim), "x", ms=3, color=MUTED, label="removed by screening")
        ax.plot(h[ok], r[ok], ".", ms=3, color=LINE, label="kept")
        for b in range(1, len(settings.DAYS)):
            ax.axvline(24 * b, color=MUTED, lw=0.6, ls=":")
        if k == "reducedDynamic":
            for a in arcs:
                ax.axvline((a - settings.TIME_START) * 24, color=ARC, lw=0.6, ls="--")
        ax.set_ylim(-lim, lim)
        ax.set_ylabel("cm", color=INK)
        ax.set_title(labels[k], fontsize=9, color=INK, loc="left")
        ax.grid(color=GRID, lw=0.8)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values():
            s.set_color(GRID)
    axes[0, 0].legend(fontsize=7, loc="upper right")
    axes[-1, 0].set_xlabel(f"Hours since {settings.START} 00:00 (GPS time)", color=INK)
    axes[-1, 0].set_xlim(0, 24 * len(settings.DAYS))
    fig.suptitle(f"CHAMP SLR residuals (measured - computed range), {len(common)} normal points common to all orbits"
                 f"\nvalues beyond ±{lim:.0f} cm drawn at the edge" + ("; dashed: reduced-dynamic arc starts"
                                                                       if len(arcs) else ""),
                 color=INK, x=0.01, ha="left", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------------------------------------------ main

def validate(run_dir, out_dir, exe, data_dir, orbit_sets, arcs):
    """orbit_sets: {"kinematic": [daily files], "reducedDynamic": [...]} (ours). Returns (lines, files used, N)."""
    run_dir, out_dir = Path(run_dir).resolve(), Path(out_dir).resolve()
    check_isolation(run_dir)
    slr_rel = f"{out_dir.relative_to(run_dir).as_posix()}/slr"
    slr_dir = run_dir / slr_rel
    slr_dir.mkdir(parents=True, exist_ok=True)
    tag = out_dir.name
    lines, used = ["", "[10] SLR validation (SLR data used only here)"], []

    cstg, notes = normal_point_files(settings.DAYS)
    lines += ["  " + n for n in notes]
    used += [str(f) for f in cstg]
    if not cstg:
        return lines + ["  no SLR normal points available; SLR validation skipped"], used, 0

    # orbits: ours as they are; TU Graz's converted to GROOPS-readable files (validation only)
    labels = {"kinematic": "our kinematic orbit", "reducedDynamic": "our reduced-dynamic orbit",
              "tugKinematic": "TU Graz kinematic orbit", "tugReducedDynamic": "TU Graz reduced-dynamic orbit"}
    templ = {}
    for k, files in orbit_sets.items():
        templ[k] = str(Path(files[0]).resolve().relative_to(run_dir)).replace(settings.DAYS[0], D)
    for k, kind in (("tugKinematic", "kinematicOrbit"), ("tugReducedDynamic", "reducedDynamicOrbit")):
        ok = all(tug_orbit(kind, day, slr_dir / k / f"orbitInput_{day}.txt") for day in settings.DAYS)
        if ok:
            templ[k] = f"{slr_rel}/{k}/orbitInput_{D}.txt"
        else:
            lines.append(f"  {labels[k]} not available for all days; not used")
    labels = {k: v for k, v in labels.items() if k in templ}

    # script a: platform + normal points
    s02 = (run_dir / champ.ORDER[1]).read_text()
    s03 = (run_dir / champ.ORDER[3]).read_text()
    apriori, star = champ.leo_files(s03)
    sa = f"10aSlrNormalPoints.{tag}.xml"
    (run_dir / sa).write_text(script_normal_points(slr_rel, cstg))
    print("[10] GROOPS: SLR normal points")
    run_groops.run_scripts(run_dir, [sa], data_dir, exe, {})
    raw = sorted(str(p.relative_to(run_dir)) for p in (slr_dir / "np" / "raw").glob("*.dat"))
    np_stations = sorted({Path(f).stem.split("_")[-1] for f in raw if Path(f).name.startswith("np_")})

    # stations: in the GROOPS SLRF2020 station list, with station info and position files (downloaded per file)
    have = set(download.fetch_data_file(data_dir, "slr/stations/stationList.slrf2020.txt").read_text().split())
    stations = []
    for s in np_stations:
        if s not in have:
            lines.append(f"  station {s}: not in the GROOPS SLRF2020 station list; not used")
            continue
        try:
            for rel in (f"slr/stations/stationInfo/stationInfo.{s}.xml",
                        f"slr/stations/position/slrf2020_CM/stationPosition.{s}.dat"):
                used.append(str(download.fetch_data_file(data_dir, rel)))
            stations.append(s)
        except SystemExit as e:
            lines.append(f"  station {s}: station file not available ({e}); not used")
    if not stations:
        return lines + ["  no usable SLR station; SLR validation skipped"], used, 0
    (slr_dir / "stationList.txt").write_text("\n".join(stations) + "\n")
    (slr_dir / "satelliteList.txt").write_text(SAT + "\n")

    # TU Graz settings: station tides/loading (GNSS PPP scenario), Earth rotation (script 03), attitude resampling (02)
    ppp_script, station_elems, extra_globals = tug_station_settings()
    if not any(e.tag == "inputfileDeformationLoadLoveNumber" for e in station_elems):   # MUSTSET in GROOPS:
        station_elems.append(_e("inputfileDeformationLoadLoveNumber",                    # GROOPS default value
                                "{groopsDataDir}/loading/deformationLoveNumbers_CM_Gegout97.txt"))
    station_elems.sort(key=_station_tidy)
    earth_rotation = next(ET.fromstring(s03).iter("GnssProcessing")).find("earthRotation")   # as in the orbits
    star_resample = next(p for p in champ._programs_with(ET.fromstring(s02), "InstrumentResample")
                         if p.find("InstrumentResample/outputfileInstrument").text == star)
    sb = f"10bSlrProcessing.{tag}.xml"
    text = script_processing(slr_rel, raw, stations, templ, star, star_resample, earth_rotation, station_elems,
                             extra_globals)
    (run_dir / sb).write_text(text)
    for rel in run_groops.required_data_files(run_dir / sb):     # files of the TU Graz settings, per file
        from core import files_used
        paths = [rel.replace("{station}", s) for s in stations] if "{station}" in rel else [rel]
        paths = sorted({files_used.resolve(p, {}, day).replace("*", "{") if "{" in p else p
                        for p in paths for day in settings.DAYS})        # {loopTime:...} -> each day
        for p in paths:
            if "{" in p:
                sys.exit(f"[SLR] cannot resolve GROOPS data path {p} (TU Graz settings in {ppp_script}). Stopped.")
            try:
                used.append(str(download.fetch_data_file(data_dir, p)))
            except SystemExit as e:
                sys.exit(f"[SLR] GROOPS data file {p} not available: {e}. Stopped.")
    print("[10] GROOPS: SLR residuals")
    run_groops.run_scripts(run_dir, [sb], data_dir, exe, {})

    stat_lines, n = statistics(slr_dir, labels, settings.DAYS, arcs, out_dir / "slr_residuals.png")
    lines += [f"  stations: {', '.join(stations)}", f"  TU Graz station tide/loading settings from {ppp_script}",
              f"  scripts: {sa}, {sb}; residual files: {slr_dir}"] + stat_lines
    lines.append(f"[check 10] SLR normal points common to all orbits: {n}")
    return lines, used, n

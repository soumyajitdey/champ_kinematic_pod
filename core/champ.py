"""CHAMP inputs and GROOPS scripts: GPS-only kinematic PPP, then reduced-dynamic POD (confirmed 2026-10-10/11).

GROOPS calculations are never reimplemented. TU Graz's XML scripts (GRACE-FO scenarios, release of the TU Graz
server) are executed by GROOPS; only GRACE-FO -> CHAMP adaptations and the confirmed pipeline changes are applied
(XML edited at run time, the downloaded originals stay untouched in work/scenarios/):

  all scripts   gracefo1/gracefo -> champ (TU Graz CHAMP metadata and satellite model in the GROOPS data)
  all scripts   TU Graz's daily loop unchanged (CHANGED 2026-10-11): each day uses only its own input files,
                including its own GPS signal biases (OSB). The old code's one-loop-over-the-period with the
                middle day's bias file gave wrong integer ambiguities on 2010-05-01 (L1W phase biases differ by
                0.05-0.46 cycles between 2010-05-01 and 05-02).
  01 products   repro3: unchanged. final/ultra: product file names; GPS attitude and biases off (old code)
  02 convert    RINEX = GFZ CH-OG-1-SST + type mapping (old code); attitude reader GraceL1b2StarCamera ->
                Champ2AccStar (old code); orbit reader GraceL1b2Orbit -> Sp3Format2Orbit of the RTKLIB rough
                positions (old GPS-only code). Polynomial option: the a priori orbit resampling to the receiver
                epochs uses a least squares polynomial fit + velocities (old GPS-only code). Dynamic option: that
                resampling is done in script 02b on the dynamically fitted orbit, with TU Graz's original setting.
  02b a priori  NEW. Dynamic option: TU Graz reduced-dynamic script 03groopsVariational.xml (force models,
                stochastic pulses, iterations unchanged) fitted to the RTKLIB rough positions, then TU Graz's
                original resampling and TU Graz's own InstrumentSynchronize of script 02 (moved here, unchanged).
                Both options: text copy of the a priori orbit for the per-step check.
  03 kinematic  wavelengthFactor 0.5 -> 1 (CHAMP RINEX header); final/ultra: float ambiguities (old code)
  04 variational NEW 2026-10-11 (reduced-dynamic POD, version 2): TU Graz reduced-dynamic 03groopsVariational.xml
                (force models, stochastic pulses, iterations unchanged) fitted to the kinematic positions of script 03
                with their 3x3 covariances (replaces GRACE-FO's GNV1B orbit); TU Graz's original resampling and
                synchronization of script 02 give the a priori orbit at the receiver epochs.
  05 RD GNSS    NEW 2026-10-11: TU Graz reduced-dynamic 04groopsGnssProcessing.xml (leoDynamicOrbits); same CHAMP
                adaptations as script 03. Files of 04/05: data/<day>/champReducedDynamic/, output/<day>/reducedDynamic/.

Synchronization (CHANGED 2026-10-11, items 14/15): TU Graz's script 02 ends with InstrumentSynchronize of GPS
observations, a priori orbit and attitude (identical epochs, required by GROOPS: whole receiver disabled otherwise,
gnssReceiverGeneratorLowEarthOrbiter.cpp l.139-141). The package's own extra synchronization is removed.
Polynomial option: TU Graz's program stays where it is. Dynamic option: the a priori orbit exists only after the
fit in 02b, so TU Graz's program is moved, unchanged, to the end of 02b (otherwise it would synchronize against
the unfitted rough positions and delete GPS observations at epochs without a rough position).
"""
import copy
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

from core import download, settings

ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")   # keep the xsi prefix of TU Graz's XML
D = "{loopTime:%D}"
SAT = settings.SATELLITE
INPUTS = settings.INPUTS
OBS_TYPES = """# CHAMP RINEX 2.10 (GFZ CH-OG-1-SST) -> RINEX 3 types
# Source: GFZ (Koehler 2001), "RINEX format observable extensions for CHAMP SST Data" (CH-RINEX-EXT):
#   L1  = carrier phase on C/A channel, always available -> L1C
#   LP1 = phase measurement on L1, output only if P1 enabled -> L1W
#   SA  = SNR of C/A channel -> S1C; S1/S2 "as in standard RINEX" -> S1W/S2W (P channel: inferred, not stated)
  C1      C1C
  P1      C1W
  P2      C2W
  L1      L1C
  LP1     L1W
  L2      L2W
  SA      S1C
  S1      S1W
  S2      S2W
"""
# GROOPS data used by these scripts but not by the TU Graz scenario scripts (old code)
EXTRA_DATA = ["gnss/receiverLowEarthOrbiter/champ", "satelliteModel/champ_satelliteModel.xml",
              "gnss/transmitter/attitudeInfo", "gnss/transmitter/transmitterInfo/igs/igs20"]
CDDIS_BRDC = "https://cddis.nasa.gov/archive/gnss/data/daily/{y}/{doy:03d}/{yy:02d}n/brdc{doy:03d}0.{yy:02d}n.Z"


# =====================================================================================================
# inputs
# =====================================================================================================

def brdc(day):
    """GPS broadcast navigation file of a day in work/inputs/brdc (plain, .gz or .Z), or None."""
    d = date.fromisoformat(day)
    stem = f"brdc{d.timetuple().tm_yday:03d}0.{d.year % 100:02d}n"
    for ext in ("", ".gz", ".Z"):
        f = INPUTS / "brdc" / (stem + ext)
        if f.is_file():
            return f
    return None


def missing_brdc():
    out = []
    for day in settings.DAYS:
        if brdc(day) is None:
            d = date.fromisoformat(day)
            url = CDDIS_BRDC.format(y=d.year, doy=d.timetuple().tm_yday, yy=d.year % 100)
            out.append(f"{INPUTS / 'brdc' / Path(url).name}\n      download: {url}")
    return out


def _first_member(zpath, test):
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            text = z.read(m).decode("ascii", "replace")
            if test(text):
                return text
    sys.exit(f"[CHAMP] no usable file in {zpath}")


def get_champ_inputs():
    """Per day in work/inputs/champ/: CH-OG-1-SST_<day>.rnx, ACC_<day>.dat (old code; existing files kept)."""
    from core import legacy_download as L
    out = INPUTS / "champ"
    out.mkdir(parents=True, exist_ok=True)
    dl = settings.DOWNLOADS / "champ"
    for k in ("RINEX", "ACC"):
        (dl / k).mkdir(parents=True, exist_ok=True)
    rep = L.Report()
    for day in settings.DAYS:
        d = date.fromisoformat(day)
        rnx = out / f"CH-OG-1-SST_{day}.rnx"
        if not rnx.is_file():
            z = L.fetch_champ_rinex(d, str(dl / "RINEX"), rep)
            if not z:
                sys.exit(f"[CHAMP] RINEX {day} failed: " + "; ".join(r[3] for r in rep.failed()))
            rnx.write_text(_first_member(z, L._is_rnx))
        acc = out / f"ACC_{day}.dat"
        if not acc.is_file():
            z = L.fetch_champ_acc(d, str(dl / "ACC"), rep)
            if not z:
                sys.exit(f"[CHAMP] ACC {day} failed: " + "; ".join(r[3] for r in rep.failed()))
            text = _first_member(z, L._is_asc)
            head = "\n".join(l for l in text.splitlines()[:60] if l.startswith("+"))
            if "+reference" in head and "utc" in head.split("+reference")[1].split("\n")[0].lower():
                sys.exit(f"[CHAMP] {z}: time reference is UTC; GROOPS Champ2AccStar expects GPS time. Stopped.")
            if "\natt " not in text:
                sys.exit(f"[CHAMP] {z}: no attitude ('att') records; Champ2AccStar would give no star camera data.")
            acc.write_text(text)
    return out


# =====================================================================================================
# XML helpers
# =====================================================================================================

def _xml(root):
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def _names(text):
    return text.replace("gracefo1", SAT).replace("gracefo", SAT)


def _programs_with(root, tag):
    return [p for p in root.iter("program") if p.find(tag) is not None]


def _loop(root):
    loop = root.find("program/LoopPrograms")
    if loop is None:
        sys.exit("[CHAMP] TU Graz script without program/LoopPrograms; script structure not as expected")
    return loop


def leo_files(s03_text):
    """(a priori orbit file, attitude file) that the kinematic GNSS processing (script 03) reads."""
    root = ET.fromstring(s03_text)
    leo = next(root.iter("lowEarthOrbiter"), None)
    if leo is None or leo.find("inputfileOrbit") is None or leo.find("inputfileStarCamera") is None:
        sys.exit("[CHAMP] lowEarthOrbiter/inputfileOrbit|inputfileStarCamera not found in 03 script")
    return leo.find("inputfileOrbit").text, leo.find("inputfileStarCamera").text


def _orbit_resample(root, apriori):
    """The InstrumentResample program of script 02 that writes the a priori orbit read by script 03."""
    progs = [p for p in _programs_with(root, "InstrumentResample")
             if (p.find("InstrumentResample/outputfileInstrument").text or "") == apriori]
    if not progs:                                                     # old code's rule
        progs = [p for p in _programs_with(root, "InstrumentResample")
                 if "_orbit_" in (p.find("InstrumentResample/outputfileInstrument").text or "")]
    if len(progs) != 1:
        sys.exit(f"[CHAMP] expected one orbit InstrumentResample in script 02 (output {apriori}), found {len(progs)}")
    return progs[0]


# =====================================================================================================
# 01 / 03: unchanged from the old code
# =====================================================================================================

def products_01(text, products):
    """TU Graz 01groopsConvert.xml for the product type (repro3: unchanged)."""
    if products == "repro3":
        return text
    root = ET.fromstring(text)
    name = {"final": "IGS0FIN", "ultra": "IGU"}[products]
    for p in _programs_with(root, "Sp3Format2Orbit"):
        sp3 = p.find("Sp3Format2Orbit")
        sp3.find("inputfile").text = f"igs/{name}_{{loopTime:%y%03O}}_ORB.SP3"
        if products == "ultra":                     # clocks are in the ultra-rapid SP3 file
            ET.SubElement(sp3, "outputfileClock").text = f"data/{D}/clock/clock_{D}.{{prn}}.dat"
    for p in _programs_with(root, "GnssClockRinex2InstrumentClock"):
        if products == "final":
            p.find("GnssClockRinex2InstrumentClock/inputfileClockRinex").text = f"igs/{name}_{{loopTime:%y%03O}}_CLK.CLK"
        else:
            p.set("disabled", "1")
    for tag in ("GnssOrbex2StarCamera", "GnssSinexBias2SignalBias"):   # no attitude / biases in these products
        for p in _programs_with(root, tag):
            p.set("disabled", "1")
    for p in root.iter("program"):                  # TU Graz's own alternative: simulated GPS attitude
        if p.get("comment", "").startswith("(alternative) simulated satellite attitude"):
            p.attrib.pop("disabled", None)
    return _xml(root)


def gnss_03(text, products):
    """TU Graz kinematic GNSS processing script for CHAMP (old code)."""
    root = ET.fromstring(text)
    for leo in root.iter("lowEarthOrbiter"):
        leo.find("wavelengthFactor").text = "1"              # CHAMP RINEX header: full-cycle L1/L2
        if products != "repro3":
            leo.find("supportsIntegerAmbiguities").text = "0"  # no satellite phase biases -> float only
    if products != "repro3":
        for sb in root.iter("signalBiases"):
            e = sb.find("inputfileSignalBiasTransmitter")
            if e is not None:
                sb.remove(e)
    return _xml(root)


# =====================================================================================================
# 02: CHAMP conversion (old GPS-only code; dynamic option: orbit resampling moved to 02b)
# =====================================================================================================

def _tug_sync(root, apriori):
    """TU Graz's InstrumentSynchronize program of script 02 (the one that contains the a priori orbit)."""
    progs = [p for p in _programs_with(root, "InstrumentSynchronize")
             if any((e.text or "") == apriori for e in p.iter("inputfileInstrument"))]
    if len(progs) != 1:
        sys.exit(f"[CHAMP] expected one InstrumentSynchronize with {apriori} in script 02, found {len(progs)}")
    return progs[0]


def convert_02(text, start_orbit, apriori):
    """TU Graz 02groopsConvertGracefo.xml with the CHAMP converters. Returns (xml text, original orbit
    resampling program of TU Graz (deep copy, before any change), TU Graz's synchronization program (deep copy;
    dynamic option: removed from 02 and run at the end of 02b; polynomial option: None, stays in 02))."""
    root = ET.fromstring(text)
    for p in _programs_with(root, "RinexObservation2GnssReceiver"):
        r = p.find("RinexObservation2GnssReceiver")
        r.find("inputfileRinexObservation").text = f"champ/CH-OG-1-SST_{D}.rnx"
        r.find("inputfileSpecialObservationTypes").text = "02observationTypes.champ.txt"
    loop = _loop(root)
    for p in _programs_with(root, "GraceL1b2Orbit"):
        g = p.find("GraceL1b2Orbit")
        out = g.find("outputfileOrbit").text
        tmp = out.replace("_orbit_", "_orbitSpp_")
        p.remove(g)
        s = ET.SubElement(p, "Sp3Format2Orbit")
        ET.SubElement(s, "outputfileOrbit").text = tmp
        if start_orbit == "dynamic":                                            # NEW: 3 m covariances (SP3 EP)
            ET.SubElement(s, "outputfileCovariance").text = spp_covariance(out)
        ET.SubElement(s, "satelliteIdentifier").text = "L06"
        s.append(g.find("earthRotation"))
        ET.SubElement(s, "inputfile").text = f"champ/SPP_{D}.sp3"              # RTKLIB rough positions
        cat = ET.Element("program", {"comment": out + " (sorted, duplicate epochs removed)"})
        c = ET.SubElement(cat, "InstrumentConcatenate")
        ET.SubElement(c, "outputfile").text = out
        ET.SubElement(c, "inputfile").text = tmp
        ET.SubElement(c, "sort").text = "1"
        rd = ET.SubElement(c, "removeDuplicates")
        ET.SubElement(ET.SubElement(rd, "keepFirst"), "margin").text = "1e-5"
        parent = {c2: p2 for p2 in root.iter() for c2 in p2}[p]
        parent.insert(list(parent).index(p) + 1, cat)
    prog = _orbit_resample(root, apriori)
    original = copy.deepcopy(prog)
    if start_orbit == "polynomial":                     # a priori orbit = least squares polynomial (old code)
        r = prog.find("InstrumentResample")
        m = r.find("method")
        for c in list(m):
            m.remove(c)
        ls = ET.SubElement(m, "leastSquaresPolynomialFit")
        ET.SubElement(ls, "polynomialDegree").text = str(settings.POLY_DEGREE)
        ET.SubElement(ls, "maxDataPointDistance").text = str(settings.POLY_WINDOW)
        ET.SubElement(ls, "maxExtrapolationDistance").text = str(settings.POLY_EXTRAPOLATION)
        out = r.find("outputfileInstrument").text
        vel = ET.Element("program", {"comment": out + " (velocities)"})
        v = ET.SubElement(vel, "OrbitAddVelocityAndAcceleration")
        ET.SubElement(v, "outputfileOrbit").text = out
        ET.SubElement(v, "inputfileOrbit").text = out
        ET.SubElement(v, "polynomialDegree").text = str(settings.VELOCITY_DEGREE)
        parent = {c2: p2 for p2 in root.iter() for c2 in p2}[prog]
        parent.insert(list(parent).index(prog) + 1, vel)
    else:                                               # dynamic: resampling runs in 02b on the fitted orbit
        prog.set("disabled", "1")
        prog.set("comment", (prog.get("comment") or "") + " [dynamic option: runs in 02b on the fitted orbit]")
    sync = None                                                                 # CHANGED 2026-10-11 (item 15)
    if start_orbit == "dynamic":                        # TU Graz's synchronization moves to the end of 02b
        sp = _tug_sync(root, apriori)
        sync = copy.deepcopy(sp)
        parent = {c2: p2 for p2 in root.iter() for c2 in p2}[sp]
        parent.remove(sp)
    for p in _programs_with(root, "GraceL1b2StarCamera"):
        g = p.find("GraceL1b2StarCamera")
        out = g.find("outputfileStarCamera").text
        p.remove(g)
        c = ET.SubElement(p, "Champ2AccStar")
        ET.SubElement(c, "outputfileStarCamera").text = out
        ET.SubElement(c, "inputfile").text = f"champ/ACC_{D}.dat"
    return _xml(root), original, sync


def spp_orbit(text02):
    """File of the RTKLIB rough positions of the day after conversion in script 02 (CRF)."""
    root = ET.fromstring(text02)
    cats = [p.find("InstrumentConcatenate/outputfile").text for p in _programs_with(root, "InstrumentConcatenate")
            if any("_orbitSpp_" in (e.text or "") for e in p.iter("inputfile"))]
    if len(cats) != 1:
        sys.exit("[CHAMP] rough-position orbit file not found in script 02")
    return cats[0]


def spp_covariance(orbit_file):
    return orbit_file.replace("_orbit_", "_covarianceSpp_")


# =====================================================================================================
# 02b: a priori orbit (dynamic fit + TU Graz synchronization) + text copy for the check
# =====================================================================================================

CHECK_APRIORI = f"checks/{SAT}_aprioriOrbit_{D}.txt"


def _check_copy(apriori):
    """Text copy of the a priori orbit for the per-step check (CHANGED 2026-10-11, item 14: the package's own
    InstrumentSynchronize removed; TU Graz's synchronization of script 02 is used)."""
    return ET.fromstring(f"""<program comment="{CHECK_APRIORI} (text copy for the per-step check)">
<InstrumentConcatenate><outputfile>{CHECK_APRIORI}</outputfile><inputfile>{apriori}</inputfile></InstrumentConcatenate>
</program>""")


def _merge_globals(dst_root, src_root):
    """Copy <global> variables of src missing in dst (the copied 02 program may use them)."""
    gs, gd = src_root.find("global"), dst_root.find("global")
    if gs is None:
        return
    if gd is None:
        gd = ET.Element("global")
        dst_root.insert(0, gd)
    have = {e.get("label", e.tag) for e in gd}         # GROOPS: global elements are named by attribute 'label'
    for e in gs:
        if e.get("label", e.tag) not in have:
            gd.append(copy.deepcopy(e))


def apriori_02b_polynomial(text02, apriori):
    """Script 02b for the polynomial option: text copy of the a priori orbit only (same daily loop as script 02)."""
    root = ET.fromstring(text02)
    loop = _loop(root)
    for p in loop.findall("program"):
        loop.remove(p)
    loop.append(_check_copy(apriori))
    return _xml(root)


def _resample_grid(out, inp, degree, span):
    return ET.fromstring(f"""<program comment="{out} (uniform {settings.DYN_SAMPLING}-s grid, gaps up to 30 s filled)">
<InstrumentResample>
<outputfileInstrument>{out}</outputfileInstrument>
<inputfileInstrument>{inp}</inputfileInstrument>
<method><fillGapsLeastSquaresPolynomialFit><polynomialDegree>{degree}</polynomialDegree><maxDataGap>{settings.DYN_MAX_GAP}</maxDataGap><maxDataSpan>{span}</maxDataSpan><margin>1e-5</margin></fillGapsLeastSquaresPolynomialFit></method>
<timeSeries><uniformSampling><timeStart>loopTime</timeStart><timeEnd>loopTimeEnd</timeEnd><sampling>{settings.DYN_SAMPLING}/86400</sampling></uniformSampling></timeSeries>
</InstrumentResample>
</program>""")


def apriori_02b_dynamic(var_text, text02, original_resample, tug_sync, apriori, star):
    """Script 02b for the dynamic option, built from TU Graz 03groopsVariational.xml (reduced-dynamic scenario;
    adapted from the old code's core/script_c.py). Force models, stochastic pulses, iteration settings unchanged.
      1. InstrumentResample  rough positions -> uniform 10-s grid; gaps up to 30 s of missing data filled by
                             fillGapsLeastSquaresPolynomialFit; longer gaps stay empty (integration start only)
      2. OrbitAddVelocityAndAcceleration  velocities of that grid orbit
      3. InstrumentResample  attitude -> same grid, same gap rule
      4. InstrumentSynchronize  grid orbit + attitude: new arc at every remaining gap and after 24 h; arcs with
                             fewer than 10 epochs rejected; rough positions + 3x3 covariances (3 m) split into the
                             same arcs (irregularData)
      5. PreprocessingVariationalEquation (TU Graz)       force-model orbit integration per arc
      6. PreprocessingVariationalEquationOrbitFit (TU Graz) fit to the rough positions, 20-min pulses
      7. TU Graz's original InstrumentResample of script 02: fitted orbit -> receiver epochs (= a priori orbit)
      8. TU Graz's InstrumentSynchronize of script 02 (unchanged): GPS observations + a priori orbit + attitude;
         text copy for the check
    """
    root = ET.fromstring(var_text)
    _merge_globals(root, ET.fromstring(text02))
    loop = _loop(root)
    var_progs = _programs_with(loop, "PreprocessingVariationalEquation")
    fit_progs = _programs_with(loop, "PreprocessingVariationalEquationOrbitFit")
    if not var_progs or not fit_progs:
        sys.exit("[CHAMP] PreprocessingVariationalEquation / ...OrbitFit not found in 03groopsVariational.xml")
    first_dir = root.find("program/LoopPrograms/program/FileCreateDirectories/directory")
    if first_dir is None:
        sys.exit("[CHAMP] FileCreateDirectories not found in 03groopsVariational.xml")
    data = f"data/{D}/{first_dir.text.rstrip('/').split('/')[-1]}/{SAT}_"
    spp = spp_orbit(text02)
    orbit_grid = data + f"orbitDynamicGrid_{D}.dat"
    star_grid = data + f"starCameraDynamicGrid_{D}.dat"
    obs_arcs = data + f"orbitSppArcs_{D}.dat"
    cov_arcs = data + f"covarianceSppArcs_{D}.dat"
    fitted = data + f"orbitDynamicFit_{D}.dat"

    new = [
        _resample_grid(orbit_grid, spp, settings.DYN_FILL_DEGREE, settings.DYN_FILL_SPAN),
        ET.fromstring(f"""<program comment="{orbit_grid} (velocities)">
<OrbitAddVelocityAndAcceleration><outputfileOrbit>{orbit_grid}</outputfileOrbit><inputfileOrbit>{orbit_grid}</inputfileOrbit><polynomialDegree>{settings.VELOCITY_DEGREE}</polynomialDegree></OrbitAddVelocityAndAcceleration>
</program>"""),
        _resample_grid(star_grid, star, 1, 20),
        ET.fromstring(f"""<program comment="arcs: new arc at gaps of more than 30 s missing data, at most 24 h, at least {settings.DYN_MIN_ARC_EPOCHS} epochs">
<InstrumentSynchronize>
<data><outputfileInstrument>{orbit_grid}</outputfileInstrument><inputfileInstrument>{orbit_grid}</inputfileInstrument></data>
<data><outputfileInstrument>{star_grid}</outputfileInstrument><inputfileInstrument>{star_grid}</inputfileInstrument></data>
<margin>1e-5</margin>
<minArcLength>{settings.DYN_MIN_ARC_EPOCHS}</minArcLength>
<maxArcLength>{settings.DYN_MAX_ARC_EPOCHS}</maxArcLength>
<timeIntervals><uniformSampling><timeStart>loopTime</timeStart><timeEnd>loopTimeEnd</timeEnd><sampling>loopTimeEnd-loopTime</sampling></uniformSampling></timeIntervals>
<irregularData><outputfileInstrument>{obs_arcs}</outputfileInstrument><inputfileInstrument>{spp}</inputfileInstrument></irregularData>
<irregularData><outputfileInstrument>{cov_arcs}</outputfileInstrument><inputfileInstrument>{spp_covariance(spp)}</inputfileInstrument></irregularData>
</InstrumentSynchronize>
</program>"""),
    ]
    i = list(loop).index(var_progs[0])
    for k, p in enumerate(new):
        loop.insert(i + k, p)

    v0 = var_progs[0].find("PreprocessingVariationalEquation")
    v0.find("inputfileOrbit").text = orbit_grid
    for vp in var_progs:                                     # every integration uses the CHAMP attitude grid
        vp.find("PreprocessingVariationalEquation/inputfileStarCamera").text = star_grid
    for fp in fit_progs:                                     # every fit uses the rough positions as observations
        f = fp.find("PreprocessingVariationalEquationOrbitFit")
        f.find("inputfileOrbit").text = obs_arcs
        cov = f.find("inputfileCovariancePodEpoch")
        if cov is None:
            cov = ET.Element("inputfileCovariancePodEpoch")
            f.insert(list(f).index(f.find("inputfileOrbit")) + 1, cov)
        cov.text = cov_arcs
    last = fit_progs[-1].find("PreprocessingVariationalEquationOrbitFit")
    if last.find("outputfileOrbit") is None:
        o = ET.Element("outputfileOrbit")
        last.insert(list(last).index(last.find("outputfileVariational")) + 1, o)
    last.find("outputfileOrbit").text = fitted

    res = copy.deepcopy(original_resample)                  # TU Graz's original resampling, input = fitted orbit
    res.attrib.pop("disabled", None)
    res.set("comment", f"{apriori} (fitted orbit -> receiver epochs, TU Graz's original resampling)")
    res.find("InstrumentResample/inputfileInstrument").text = fitted
    i = list(loop).index(fit_progs[-1])
    loop.insert(i + 1, res)
    loop.insert(i + 2, tug_sync)                            # CHANGED 2026-10-11 (item 15): TU Graz's program
    loop.insert(i + 3, _check_copy(apriori))
    return _xml(root)


# =====================================================================================================
# NEW 2026-10-11: reduced-dynamic POD (confirmed: version 2, after the kinematic PPP, same run folder)
#   04 = TU Graz reduced-dynamic scenario script 03groopsVariational.xml
#   05 = TU Graz reduced-dynamic scenario script 04groopsGnssProcessing.xml
# The kinematic PPP orbit of script 03 replaces GRACE-FO's GNV1B orbit as a priori orbit. All CHAMP files of the
# reduced-dynamic part are written to data/<day>/champReducedDynamic/ and output/<day>/reducedDynamic/, so no file
# of the kinematic part is overwritten.
# =====================================================================================================

CHAMP_DATA = f"data/{D}/{SAT}"
RD_DATA = f"data/{D}/{SAT}ReducedDynamic"
RD_OUTPUT = f"output/{D}/reducedDynamic"
CHECK_APRIORI_RD = f"checks/{SAT}_aprioriOrbitReducedDynamic_{D}.txt"


def _rd_path(p):
    """data/<day>/champ/... -> data/<day>/champReducedDynamic/... (other paths unchanged)."""
    if p == CHAMP_DATA or p.startswith(CHAMP_DATA + "/"):
        return RD_DATA + p[len(CHAMP_DATA):]
    return p


def _rd_paths(node):
    for e in node.iter():
        if e.text and e.text.strip():
            e.text = _rd_path(e.text.strip())
        if e.get("comment"):                                   # program comments (labels only)
            c = e.get("comment")
            e.set("comment", RD_DATA + c[len(CHAMP_DATA):] if c == CHAMP_DATA or c.startswith(CHAMP_DATA + "/") else c)


def kinematic_outputs(s03_text):
    """(kinematic positions file, 3x3 epoch covariance file) written by the kinematic script 03."""
    root = ET.fromstring(s03_text)
    kp = next(root.iter("kinematicPositions"), None)
    pos = kp.find("outputfilePositions") if kp is not None else None
    cov = kp.find("outputfileCovarianceEpoch") if kp is not None else None
    if pos is None or cov is None or not (pos.text or "").strip() or not (cov.text or "").strip():
        sys.exit("[CHAMP] kinematicPositions/outputfilePositions|outputfileCovarianceEpoch not found in 03 script")
    return pos.text.strip(), cov.text.strip()


def rd_variational_04(var_text, text02, tug_resample, tug_sync, apriori, star, receiver, kin_pos, kin_cov):
    """Script 04: TU Graz reduced-dynamic 03groopsVariational.xml with the kinematic orbit as a priori orbit.
    Force models, stochastic pulses (20 min) and iterations of TU Graz unchanged. Per day:
      1. FileCreateDirectories (TU Graz)                 data/<day>/champReducedDynamic
      2. InstrumentResample      kinematic positions -> uniform 10-s grid; gaps up to 30 s missing data filled
                                 (fillGapsLeastSquaresPolynomialFit, same settings as the dynamic a priori option)
      3. OrbitAddVelocityAndAcceleration  velocities of the grid orbit (drag force needs the velocity)
      4. InstrumentResample      attitude of the kinematic run -> same grid
      5. InstrumentSynchronize   grid orbit + attitude: new arc at every remaining gap (GROOPS integrator needs equally
                                 spaced epochs within an arc, preprocessingVariationalEquation.cpp: deltaT =
                                 T/(epochCount-1)); kinematic positions + their 3x3 covariances split into the same arcs
      6. PreprocessingVariationalEquation (TU Graz)       orbit integration per arc
      7. PreprocessingVariationalEquationOrbitFit (TU Graz) fit to the kinematic positions, weighted with their 3x3
                                 covariances (GROOPS: inputfileCovariancePodEpoch; Huber downweighting of outliers)
      8. TU Graz's original InstrumentResample of script 02: fitted orbit -> receiver epochs (GRACE-FO: GNV1B)
      9. InstrumentSynchronize   GPS observations, a priori orbit and attitude of the receiver epochs are split into
                                 the arcs of the fitted orbit; epochs outside these arcs are removed (irregularData).
                                 Required: GROOPS leoDynamicOrbits stops with 'no variational arc found' for a usable
                                 epoch outside all arcs (variationalEquationFromFile.cpp, getArc)
     10. TU Graz's InstrumentSynchronize of script 02 (unchanged; files in champReducedDynamic)
     11. text copy of the a priori orbit for check 7
    """
    root = ET.fromstring(var_text)
    _merge_globals(root, ET.fromstring(text02))
    loop = _loop(root)
    _rd_paths(loop)                                                    # all CHAMP files -> champReducedDynamic
    var_progs = _programs_with(loop, "PreprocessingVariationalEquation")
    fit_progs = _programs_with(loop, "PreprocessingVariationalEquationOrbitFit")
    if not var_progs or not fit_progs:
        sys.exit("[CHAMP] PreprocessingVariationalEquation / ...OrbitFit not found in 03groopsVariational.xml")
    data = f"{RD_DATA}/{SAT}_"
    orbit_grid = data + f"orbitKinematicGrid_{D}.dat"
    star_grid = data + f"starCameraKinematicGrid_{D}.dat"
    obs_arcs = data + f"orbitKinematicArcs_{D}.dat"
    cov_arcs = data + f"covarianceKinematicArcs_{D}.dat"
    fitted = data + f"orbitDynamicFit_{D}.dat"
    rd_apriori, rd_star, rd_receiver = _rd_path(apriori), _rd_path(star), _rd_path(receiver)

    new = [
        _resample_grid(orbit_grid, kin_pos, settings.DYN_FILL_DEGREE, settings.DYN_FILL_SPAN),
        ET.fromstring(f"""<program comment="{orbit_grid} (velocities)">
<OrbitAddVelocityAndAcceleration><outputfileOrbit>{orbit_grid}</outputfileOrbit><inputfileOrbit>{orbit_grid}</inputfileOrbit><polynomialDegree>{settings.VELOCITY_DEGREE}</polynomialDegree></OrbitAddVelocityAndAcceleration>
</program>"""),
        _resample_grid(star_grid, star, 1, 20),
        ET.fromstring(f"""<program comment="arcs: new arc at gaps of more than 30 s missing data, at most 24 h, at least {settings.DYN_MIN_ARC_EPOCHS} epochs">
<InstrumentSynchronize>
<data><outputfileInstrument>{orbit_grid}</outputfileInstrument><inputfileInstrument>{orbit_grid}</inputfileInstrument></data>
<data><outputfileInstrument>{star_grid}</outputfileInstrument><inputfileInstrument>{star_grid}</inputfileInstrument></data>
<margin>1e-5</margin>
<minArcLength>{settings.DYN_MIN_ARC_EPOCHS}</minArcLength>
<maxArcLength>{settings.DYN_MAX_ARC_EPOCHS}</maxArcLength>
<timeIntervals><uniformSampling><timeStart>loopTime</timeStart><timeEnd>loopTimeEnd</timeEnd><sampling>loopTimeEnd-loopTime</sampling></uniformSampling></timeIntervals>
<irregularData><outputfileInstrument>{obs_arcs}</outputfileInstrument><inputfileInstrument>{kin_pos}</inputfileInstrument></irregularData>
<irregularData><outputfileInstrument>{cov_arcs}</outputfileInstrument><inputfileInstrument>{kin_cov}</inputfileInstrument></irregularData>
</InstrumentSynchronize>
</program>"""),
    ]
    i = list(loop).index(var_progs[0])
    for k, p in enumerate(new):
        loop.insert(i + k, p)

    v0 = var_progs[0].find("PreprocessingVariationalEquation")
    v0.find("inputfileOrbit").text = orbit_grid
    for vp in var_progs:                                     # every integration uses the CHAMP attitude grid
        vp.find("PreprocessingVariationalEquation/inputfileStarCamera").text = star_grid
    for fp in fit_progs:                                     # every fit uses the kinematic positions as observations
        f = fp.find("PreprocessingVariationalEquationOrbitFit")
        f.find("inputfileOrbit").text = obs_arcs
        cov = f.find("inputfileCovariancePodEpoch")
        if cov is None:
            cov = ET.Element("inputfileCovariancePodEpoch")
            f.insert(list(f).index(f.find("inputfileOrbit")) + 1, cov)
        cov.text = cov_arcs
    last = fit_progs[-1].find("PreprocessingVariationalEquationOrbitFit")
    if last.find("outputfileOrbit") is None:
        o = ET.Element("outputfileOrbit")
        last.insert(list(last).index(last.find("outputfileVariational")) + 1, o)
    last.find("outputfileOrbit").text = fitted

    res = copy.deepcopy(tug_resample)                        # TU Graz's original resampling (script 02)
    res.attrib.pop("disabled", None)
    res.set("comment", f"{rd_apriori} (fitted orbit -> receiver epochs, TU Graz's original resampling)")
    r = res.find("InstrumentResample")
    r.find("outputfileInstrument").text = rd_apriori
    r.find("inputfileInstrument").text = fitted              # time series unchanged: receiver epochs (kinematic run)
    split = ET.fromstring(f"""<program comment="receiver epochs outside the arcs of the fitted orbit removed">
<InstrumentSynchronize>
<data><outputfileInstrument>{fitted}</outputfileInstrument><inputfileInstrument>{fitted}</inputfileInstrument></data>
<margin>1e-5</margin>
<timeIntervals><uniformSampling><timeStart>loopTime</timeStart><timeEnd>loopTimeEnd</timeEnd><sampling>loopTimeEnd-loopTime</sampling></uniformSampling></timeIntervals>
<irregularData><outputfileInstrument>{rd_receiver}</outputfileInstrument><inputfileInstrument>{receiver}</inputfileInstrument></irregularData>
<irregularData><outputfileInstrument>{rd_apriori}</outputfileInstrument><inputfileInstrument>{rd_apriori}</inputfileInstrument></irregularData>
<irregularData><outputfileInstrument>{rd_star}</outputfileInstrument><inputfileInstrument>{star}</inputfileInstrument></irregularData>
</InstrumentSynchronize>
</program>""")
    sync = copy.deepcopy(tug_sync)                           # TU Graz's synchronization of script 02, unchanged
    sync.attrib.pop("disabled", None)
    _rd_paths(sync)                                          # ... applied to the champReducedDynamic files
    check = ET.fromstring(f"""<program comment="{CHECK_APRIORI_RD} (text copy for the per-step check)">
<InstrumentConcatenate><outputfile>{CHECK_APRIORI_RD}</outputfile><inputfile>{rd_apriori}</inputfile></InstrumentConcatenate>
</program>""")
    i = list(loop).index(fit_progs[-1])
    for k, p in enumerate([res, split, sync, check]):
        loop.insert(i + 1 + k, p)
    return _xml(root)


def rd_gnss_05(text, products):
    """Script 05: TU Graz reduced-dynamic 04groopsGnssProcessing.xml (leoDynamicOrbits) for CHAMP.
    Same CHAMP adaptations as the kinematic script 03 (wavelengthFactor 1; final/ultra: float ambiguities).
    CHAMP input files from data/<day>/champReducedDynamic/, outputs to output/<day>/reducedDynamic/."""
    text = _names(text).replace(f"output/{D}", RD_OUTPUT)
    root = ET.fromstring(gnss_03(text, products))
    _rd_paths(root)
    if next(root.iter("leoDynamicOrbits"), None) is None:
        sys.exit("[CHAMP] leoDynamicOrbits not found in 04groopsGnssProcessing.xml")
    return _xml(root)


def rd_orbit_file(s05_text):
    """Reduced-dynamic orbit file written by script 05."""
    e = ET.fromstring(s05_text).find(".//leoDynamicOrbits/outputfileOrbit")
    if e is None or not (e.text or "").strip():
        sys.exit("[CHAMP] leoDynamicOrbits/outputfileOrbit not found in script 05")
    return e.text.strip()


def _receiver_file(s03_text):
    leo = next(ET.fromstring(s03_text).iter("lowEarthOrbiter"))
    e = leo.find("inputfileObservations")
    if e is None or not (e.text or "").strip():
        sys.exit("[CHAMP] lowEarthOrbiter/inputfileObservations not found in 03 script")
    return e.text.strip()


# =====================================================================================================
# all scripts of one run
# =====================================================================================================

ORDER = ["01groopsConvert.xml", "02groopsConvertChamp.xml", "02bgroopsAprioriOrbit.xml",
         "03groopsGnssProcessing.xml", "04groopsVariational.xml", "05groopsGnssProcessingReducedDynamic.xml"]


def scripts(start_orbit, products):
    """{script name: XML text} in execution order. TU Graz's daily loop is kept (CHANGED 2026-10-11): every day
    reads only its own files, including its own GPS signal-bias file.
    Returns (scripts, (a priori orbit, attitude, kinematic orbit, reduced-dynamic orbit) file templates)."""
    kin = download.get_scenario("kinematic")
    rd = download.get_scenario("reducedDynamic")
    s01 = products_01((kin / "01groopsConvert.xml").read_text(), products)
    s03 = _names(gnss_03((kin / "03groopsGnssProcessing.xml").read_text(), products))
    apriori, star = leo_files(s03)
    tug02 = _names((kin / "02groopsConvertGracefo.xml").read_text())
    s02, original, sync = convert_02(tug02, start_orbit, apriori)
    if start_orbit == "polynomial":
        s02b = apriori_02b_polynomial(s02, apriori)
    else:
        s02b = apriori_02b_dynamic(_names((rd / "03groopsVariational.xml").read_text()), s02, original, sync,
                                   apriori, star)
    # NEW 2026-10-11: reduced-dynamic POD after the kinematic PPP
    for a, b in ((f"{CHAMP_DATA}/", apriori), (f"{CHAMP_DATA}/", star)):
        if not b.startswith(a):
            sys.exit(f"[CHAMP] {b} is not in {CHAMP_DATA}/; script structure not as expected")
    t02 = ET.fromstring(tug02)                               # TU Graz's own programs of script 02, unmodified
    kin_pos, kin_cov = kinematic_outputs(s03)
    s04 = rd_variational_04(_names((rd / "03groopsVariational.xml").read_text()), s02,
                            copy.deepcopy(_orbit_resample(t02, apriori)), copy.deepcopy(_tug_sync(t02, apriori)),
                            apriori, star, _receiver_file(s03), kin_pos, kin_cov)
    s05 = rd_gnss_05((rd / "04groopsGnssProcessing.xml").read_text(), products)
    out = dict(zip(ORDER, [s01, s02, s02b, s03, s04, s05]))
    return out, (apriori, star, kin_pos, rd_orbit_file(s05))                  # CHANGED 2026-10-11: no window()


def template_dirs():
    return [download.get_scenario("kinematic"), download.get_scenario("reducedDynamic")]

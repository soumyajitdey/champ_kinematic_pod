"""Earth-fixed file per day (NEW 2026-10-13, user decision): position + velocity, summed SRP + ERP + 3BP acceleration
and Earth's gravitational potential, all in ONE Earth-fixed frame.

Written after the final product (core/final.py); the CRF files in final/ stay unchanged.

  final/<day>/champ_ecef_<day>.txt   one row per epoch (same epochs and arcs as the final orbit):
      MJD (GPS time) | x y z [m] | vx vy vz [m/s] | ax ay az [m/s^2] | U_grav [m^2/s^2] | lat lon [deg] alt [km] | A_ram [m^2]

Why one frame: every rotation CRF -> TRF uses the SAME earthRotation block that the POD uses (copied from the
executed script 04), so the orbit, the accelerations and the potential positions cannot disagree.

  GROOPS script 06 (written to the run folder, per day with a final file):
    1  InstrumentSynchronize     final orbit + attitude -> common epochs, ONE arc (minGap 0; GROOPS forces are
                                 per epoch, the arcs of the final file are restored in Python)
    2  InstrumentEarthRotation   rotation CRF -> TRF at those epochs (earthRotation of the POD)
    3  SimulateAccelerometer     SRP + ERP (radiationPressure block of script 04: Sun, Earth albedo, Earth infrared,
                                 satellite thermal radiation; CERES files as in the POD) + 3BP (astronomicalTide block
                                 of script 04 with usePlanets 0 = Sun and Moon). Output: satellite frame.
    4  InstrumentRotate          satellite frame -> CRF (star camera, inverseRotate 0)
    5  InstrumentRotate          CRF -> TRF (pure rotation of the acceleration vector, inverseRotate 0; no centrifugal
                                 or Coriolis terms)
    6  Orbit2EarthFixedOrbit     position and velocity CRF -> TRF (velocity = R v - omega x r). The CM -> CE
                                 degree-1 correction of this program is set to zero (factor 0), so the origin stays
                                 the Earth's centre of mass.
  Python:
    7  U_grav from the GOCO06s file named in script 04 (same file and maximum degree as the POD), evaluated at the TRF
       positions of step 6; sign convention U = -V (V = GM/r * sum ...), static field (no tides).
    8  geodetic latitude, longitude, altitude (WGS84) from the TRF positions (NEW 2026-10-13, user decision).
    9  ram area A_ram [m^2] (NEW 2026-10-14, user decision): projected area of the surfaces of the satellite model of
       script 04 (champ_satelliteModel.xml) onto the flow direction. Flow direction = TRF velocity (air co-rotates, no
       wind) rotated into the satellite frame with the star camera and Earth rotation files of step 1 and 2 (text
       copies written by InstrumentConcatenate). Plates (type 0, 3): area*max(0, n.vhat); sphere (type 1): area; the
       same rule as GROOPS miscAccelerationsAtmosphericDrag with a constant drag coefficient (cylinder: not
       implemented there either, error here). No shadowing between surfaces. C_D and mass are NOT in the file.
   10  file with the arcs of the final orbit.
"""
import copy
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from core import champ, final, run_groops, settings
from core.groops_io import arc_spans, read_instrument

SCRIPT = "06groopsEcefTerms.xml"
FOLDER = "ecef"                                   # intermediate GROOPS files in the run folder


def ecef_file(run_dir, day):
    return Path(run_dir) / final.FINAL / day / f"{settings.SATELLITE}_ecef_{day}.txt"


# =====================================================================================================
# 1. blocks of the POD (script 04) that are reused unchanged
# =====================================================================================================

def pod_blocks(s04_text):
    """Copy the settings of the POD (first PreprocessingVariationalEquation of the executed script 04)."""
    pve = next(ET.fromstring(s04_text).iter("PreprocessingVariationalEquation"), None)
    if pve is None:
        raise SystemExit("[ecef] PreprocessingVariationalEquation not found in script 04")
    forces = pve.find("forces")
    rad = [m for m in forces.findall("miscAccelerations") if m.find("radiationPressure") is not None]
    tid = [t for t in forces.findall("tides") if t.find("astronomicalTide") is not None]
    pc = forces.find("gravityfield/potentialCoefficients")
    need = {"satellite model": pve.find("inputfileSatelliteModel"), "earthRotation": pve.find("earthRotation"),
            "ephemerides": pve.find("ephemerides"), "radiationPressure": rad[0] if rad else None,
            "astronomicalTide": tid[0] if tid else None, "gravityfield potentialCoefficients": pc}
    for k, v in need.items():
        if v is None:
            raise SystemExit(f"[ecef] {k} not found in script 04; script structure not as expected")
    tide = copy.deepcopy(tid[0])
    tide.find("astronomicalTide/usePlanets").text = "0"          # 3BP = Sun and Moon only (user decision)
    return dict(sat=need["satellite model"].text.strip(), rot=copy.deepcopy(need["earthRotation"]),
                eph=copy.deepcopy(need["ephemerides"]), rad=copy.deepcopy(rad[0]), tide=tide,
                gfc=pc.find("inputfilePotentialCoefficients").text.strip(),
                gfc_degree=int(pc.find("maxDegree").text))


def _x(el):
    return ET.tostring(el, encoding="unicode").strip()


# =====================================================================================================
# 2. GROOPS script 06
# =====================================================================================================

def script_text(s04_text, days):
    b = pod_blocks(s04_text)
    rot, eph, rad, tide = _x(b["rot"]), _x(b["eph"]), _x(b["rad"]), _x(b["tide"])
    progs = ['<program comment="folder for the intermediate files"><FileCreateDirectories>'
             f'<directory>{FOLDER}</directory></FileCreateDirectories></program>']
    for d in days:
        orb_in = f"{final.FINAL}/{d}/{settings.SATELLITE}_orbit_reducedDynamic_{d}.txt"
        star = f"{champ.RD_DATA.replace(champ.D, d)}/{settings.SATELLITE}_starCameraKinematicGrid_{d}.dat"
        f = lambda n: f"{FOLDER}/{n}_{d}"                       # intermediate file names
        progs += [
            f'''<program comment="{d}: final orbit + attitude: common epochs, one arc">
<InstrumentSynchronize>
<data><outputfileInstrument>{f("orbitCrf")}.dat</outputfileInstrument><inputfileInstrument>{orb_in}</inputfileInstrument></data>
<data><outputfileInstrument>{f("starCamera")}.dat</outputfileInstrument><inputfileInstrument>{star}</inputfileInstrument></data>
<margin>1e-5</margin>
<minGap>0</minGap>
</InstrumentSynchronize>
</program>''',
            f'''<program comment="{d}: rotation CRF -> TRF at the epochs (earthRotation of the POD)">
<InstrumentEarthRotation>
<outputfileStarCamera>{f("earthRotation")}.dat</outputfileStarCamera>
{rot}
<timeSeries><instrument><inputfileInstrument>{f("orbitCrf")}.dat</inputfileInstrument></instrument></timeSeries>
</InstrumentEarthRotation>
</program>''',
            f'''<program comment="{d}: text copy of the star camera file (for the ram area in Python)">
<InstrumentConcatenate>
<outputfile>{f("starCamera")}.txt</outputfile>
<inputfile>{f("starCamera")}.dat</inputfile>
</InstrumentConcatenate>
</program>''',
            f'''<program comment="{d}: text copy of the Earth rotation file (for the ram area in Python)">
<InstrumentConcatenate>
<outputfile>{f("earthRotation")}.txt</outputfile>
<inputfile>{f("earthRotation")}.dat</inputfile>
</InstrumentConcatenate>
</program>''',
            f'''<program comment="{d}: SRP + ERP (radiationPressure of the POD) + 3BP (Sun, Moon); satellite frame">
<SimulateAccelerometer>
<outputfileAccelerometer>{f("accSatFrame")}.dat</outputfileAccelerometer>
<inputfileSatelliteModel>{b["sat"]}</inputfileSatelliteModel>
<inputfileOrbit>{f("orbitCrf")}.dat</inputfileOrbit>
<inputfileStarCamera>{f("starCamera")}.dat</inputfileStarCamera>
{rot}
{eph}
<forces>
{tide}
{rad}
</forces>
</SimulateAccelerometer>
</program>''',
            f'''<program comment="{d}: acceleration satellite frame -> CRF (star camera)">
<InstrumentRotate>
<outputfileInstrument>{f("accCrf")}.dat</outputfileInstrument>
<inputfileInstrument>{f("accSatFrame")}.dat</inputfileInstrument>
<inputfileStarCamera>{f("starCamera")}.dat</inputfileStarCamera>
<inverseRotate>0</inverseRotate>
</InstrumentRotate>
</program>''',
            f'''<program comment="{d}: acceleration CRF -> TRF (pure rotation); text file for Python">
<InstrumentRotate>
<outputfileInstrument>{f("accTrf")}.txt</outputfileInstrument>
<inputfileInstrument>{f("accCrf")}.dat</inputfileInstrument>
<inputfileStarCamera>{f("earthRotation")}.dat</inputfileStarCamera>
<inverseRotate>0</inverseRotate>
</InstrumentRotate>
</program>''',
            f'''<program comment="{d}: position and velocity CRF -> TRF (no CM->CE correction); text file for Python">
<Orbit2EarthFixedOrbit>
<outputfileOrbit>{f("orbitTrf")}.txt</outputfileOrbit>
<inputfileOrbit>{f("orbitCrf")}.dat</inputfileOrbit>
{rot}
<gravityfield><potentialCoefficients><inputfilePotentialCoefficients>{b["gfc"]}</inputfilePotentialCoefficients><minDegree>1</minDegree><maxDegree>1</maxDegree><factor>0.0</factor></potentialCoefficients></gravityfield>
</Orbit2EarthFixedOrbit>
</program>''']
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<groops>\n<global><filename label="groopsDataDir">/itsg/groops/data'
            '</filename></global>\n' + "\n".join(progs) + "\n</groops>\n")


# =====================================================================================================
# 3. Earth's gravitational potential (Python): GOCO06s, same file and degree as the POD
# =====================================================================================================

def read_gfc(path, nmax=120):
    """ICGEM .gfc file -> (GM, R, C, S); C, S fully normalized, indexed [n, m]."""
    GM = R = None
    C = np.zeros((nmax + 1, nmax + 1)); S = np.zeros((nmax + 1, nmax + 1))
    head = True
    for ln in open(path):
        w = ln.split()
        if not w:
            continue
        if head:                                                         # header lines
            if w[0] == "earth_gravity_constant": GM = float(w[1].replace("D", "E"))
            if w[0] == "radius": R = float(w[1].replace("D", "E"))
            if w[0] == "norm" and w[1] != "fully_normalized":
                raise ValueError(f"{path}: coefficients not fully normalized")
            if w[0] == "end_of_head": head = False
            continue
        if w[0] in ("trnd", "acos", "asin", "dot"):                      # time-variable terms: not handled here
            raise ValueError(f"{path}: contains time-variable terms ({w[0]})")
        if w[0] in ("gfc", "gfct"):                                      # coefficient line: key n m C S ...
            n, m = int(w[1]), int(w[2])
            if n <= nmax:
                C[n, m] = float(w[3].replace("D", "E"))
                S[n, m] = float(w[4].replace("D", "E"))
    if C[0, 0] == 0.0:                                                   # file without degree 0 -> monopole = 1
        C[0, 0] = 1.0
    return GM, R, C, S


def U_grav_full(x, y, z, gfc):
    """Gravitational potential [m^2/s^2] at Earth-fixed positions x, y, z [m] (arrays).
    U = -V, V = GM/r sum_n (R/r)^n sum_m Pbar_nm (C_nm cos m lam + S_nm sin m lam).
    Pbar_nm: fully normalized associated Legendre functions, standard forward recursion in n."""
    GM, R, C, S = gfc
    nmax = C.shape[0] - 1
    r = np.sqrt(x*x + y*y + z*z)
    s = z/r                                                              # sin(geocentric latitude)
    c = np.sqrt(x*x + y*y)/r                                             # cos(geocentric latitude)
    lam = np.arctan2(y, x)                                               # longitude
    q = R/r
    qn = [np.ones_like(r)]                                               # (R/r)^n, n = 0..nmax
    for n in range(nmax):
        qn.append(qn[-1]*q)
    V = np.zeros_like(r)
    Pmm = np.ones_like(r)                                                # Pbar_00 = 1
    for m in range(nmax + 1):
        if m == 1:
            Pmm = np.sqrt(3.0)*c                                         # Pbar_11
        elif m > 1:
            Pmm = np.sqrt((2*m + 1)/(2.0*m))*c*Pmm                       # Pbar_mm from Pbar_(m-1)(m-1)
        cm, sm = np.cos(m*lam), np.sin(m*lam)
        V += qn[m]*Pmm*(C[m, m]*cm + S[m, m]*sm)                         # term n = m
        P2, P1 = np.zeros_like(r), Pmm                                   # Pbar_(n-2)m, Pbar_(n-1)m
        for n in range(m + 1, nmax + 1):
            a = np.sqrt((2*n - 1)*(2*n + 1)/((n - m)*(n + m)))
            b = np.sqrt((2*n + 1)*(n + m - 1)*(n - m - 1)/((n - m)*(n + m)*(2*n - 3))) if n > m + 1 else 0.0
            Pn = a*s*P1 - b*P2                                           # Pbar_nm
            V += qn[n]*Pn*(C[n, m]*cm + S[n, m]*sm)
            P2, P1 = P1, Pn
    return -GM/r*V


# =====================================================================================================
# 4. output file (arcs of the final orbit restored)
# =====================================================================================================

HEADER = ("Time [MJD, GPS]          data0: pos x [m] TRF      data1: pos y [m] TRF      data2: pos z [m] TRF      "
          "data3: vel x [m/s] TRF    data4: vel y [m/s] TRF    data5: vel z [m/s] TRF    "
          "data6: acc x [m/s^2] TRF  data7: acc y [m/s^2] TRF  data8: acc z [m/s^2] TRF  data9: U_grav [m^2/s^2]  "
          "data10: lat [deg] WGS84  data11: lon [deg] WGS84  data12: alt [km] WGS84   "
          "data13: A_ram [m^2]       ")                                          # NEW 2026-10-14


def geodetic_wgs84(x, y, z):                                                # NEW 2026-10-13
    """Geodetic latitude, longitude [deg] and ellipsoidal height [km] on WGS84 from Earth-fixed x, y, z [m] (arrays).
    Iteration on the latitude (standard method, e.g. Hofmann-Wellenhof & Moritz 2006, Physical Geodesy, sect. 5.3)."""
    a, f = 6378137.0, 1/298.257223563                                       # WGS84 (NIMA TR8350.2)
    e2 = f*(2 - f)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p*(1 - e2))                                         # first guess
    with np.errstate(divide="ignore", invalid="ignore"):
        for _ in range(10):
            N = a/np.sqrt(1 - e2*np.sin(lat)**2)                            # prime vertical radius
            h = np.where(np.abs(lat) < np.pi/4, p/np.cos(lat) - N, z/np.sin(lat) - N*(1 - e2))   # stable near the poles
            lat = np.arctan2(z, p*(1 - e2*N/(N + h)))
        N = a/np.sqrt(1 - e2*np.sin(lat)**2)
        h = np.where(np.abs(lat) < np.pi/4, p/np.cos(lat) - N, z/np.sin(lat) - N*(1 - e2))
    return np.degrees(lat), np.degrees(np.arctan2(y, x)), h/1000.0

def quat2mat(q):                                                            # NEW 2026-10-14
    """GROOPS Rotary3d from quaternions (q0 = scalar part, then x, y, z; GROOPS rotary3d.cpp); q: (n,4) -> (n,3,3)."""
    q = q/np.linalg.norm(q, axis=1)[:, None]
    w, x, y, z = q.T
    R = np.empty((len(q), 3, 3))
    R[:, 0, 0] = x*x - y*y - z*z + w*w; R[:, 0, 1] = 2*(x*y - z*w);         R[:, 0, 2] = 2*(x*z + y*w)
    R[:, 1, 0] = 2*(x*y + z*w);         R[:, 1, 1] = y*y - x*x - z*z + w*w; R[:, 1, 2] = 2*(y*z - x*w)
    R[:, 2, 0] = 2*(x*z - y*w);         R[:, 2, 1] = 2*(y*z + x*w);         R[:, 2, 2] = z*z - y*y - x*x + w*w
    return R


def read_satellite_model(path):                                             # NEW 2026-10-14
    """GROOPS satelliteModel XML (fileSatelliteModel.h) -> name, mass [kg], [(type, normal (satellite frame), area [m^2])]."""
    sat = ET.parse(path).getroot().find("satellite")
    surfaces = [(int(s.find("type").text), np.array([float(s.find(f"normal/{c}").text) for c in "xyz"]),
                 float(s.find("area").text)) for s in sat.findall("surface")]
    return sat.find("satelliteName").text, float(sat.find("mass").text), surfaces


def _rows_at(t_ref, t, tol=1e-9):                                           # NEW 2026-10-14
    """Index of the epoch of t (sorted, MJD) that belongs to every epoch of t_ref; must agree within tol [d]."""
    i = np.clip(np.searchsorted(t, t_ref), 1, len(t) - 1)
    i = i - (np.abs(t[i - 1] - t_ref) < np.abs(t[i] - t_ref))
    if np.abs(t[i] - t_ref).max() > tol:
        raise SystemExit("[ecef] epochs of the star camera / Earth rotation file do not match the orbit epochs")
    return i


def ram_area(run_dir, day, t, vel, surfaces):                               # NEW 2026-10-14
    """Ram area [m^2] at epochs t [MJD], Earth-fixed velocity vel (N,3) [m/s]; see the module docstring, step 9."""
    run_dir = Path(run_dir)
    ks, ds = read_instrument(run_dir / FOLDER / f"starCamera_{day}.txt")
    kr, dr = read_instrument(run_dir / FOLDER / f"earthRotation_{day}.txt")
    if ks != "STARCAMERA" or kr != "STARCAMERA":
        raise SystemExit(f"[ecef] {day}: unexpected file types {ks}, {kr} (star camera / Earth rotation)")
    Rs = quat2mat(ds[_rows_at(t, ds[:, 0]), 1:5])                           # satellite -> CRF
    Re = quat2mat(dr[_rows_at(t, dr[:, 0]), 1:5])                           # CRF -> TRF
    M = np.einsum("nij,njk->nik", Re, Rs)                                   # satellite -> TRF
    v_sat = np.einsum("nji,nj->ni", M, vel)                                 # TRF -> satellite frame
    vhat = v_sat/np.linalg.norm(v_sat, axis=1)[:, None]                     # direction of motion relative to the air
    A = np.zeros(len(t))
    for typ, n, area in surfaces:
        if typ in (0, 3):                                                   # plate, GRACE shadow plate
            A += area*np.maximum(0.0, vhat @ n)
        elif typ == 1:                                                      # sphere
            A += area
        else:
            raise SystemExit(f"[ecef] {day}: surface type {typ} (cylinder) not implemented, as in GROOPS drag")
    return A


def _row_strings(path):
    """Raw epoch lines of a GROOPS text instrument file (arc headers skipped)."""
    lines = Path(path).read_text().splitlines()
    out, i = [], 5
    while i < len(lines) and lines[i].strip():
        n = int(lines[i])
        out += lines[i + 1:i + 1 + n]
        i += 1 + n
    return out


def write_ecef(run_dir, day, gfc, surfaces, tol=1e-9):   # CHANGED 2026-10-14: + surfaces
    """Read the TRF files of GROOPS for one day, add U_grav, write final/<day>/champ_ecef_<day>.txt.
    Returns (report line, output file)."""
    run_dir = Path(run_dir)
    orb_f = run_dir / FOLDER / f"orbitTrf_{day}.txt"
    acc_f = run_dir / FOLDER / f"accTrf_{day}.txt"
    fin_f = final.final_file(run_dir, day)
    ko, do = read_instrument(orb_f)
    ka, da = read_instrument(acc_f)
    if ko != "ORBIT" or ka != "ACCELEROMETER":
        raise SystemExit(f"[ecef] {day}: unexpected file types {ko}, {ka}")
    if do.shape[0] != da.shape[0] or np.abs(do[:, 0] - da[:, 0]).max() > tol:
        raise SystemExit(f"[ecef] {day}: orbit and acceleration epochs differ")
    t, pos, vel, acc = do[:, 0], do[:, 1:4], do[:, 4:7], da[:, 1:4]
    if not (np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(acc).all()):
        raise SystemExit(f"[ecef] {day}: non-finite values in the GROOPS output")
    U = U_grav_full(pos[:, 0], pos[:, 1], pos[:, 2], gfc)
    lat, lon, alt = geodetic_wgs84(pos[:, 0], pos[:, 1], pos[:, 2])        # NEW 2026-10-13
    A_ram = ram_area(run_dir, day, t, vel, surfaces)                       # NEW 2026-10-14
    # arcs of the final orbit: epoch belongs to the arc that contains its time
    spans = arc_spans(fin_f)
    first = np.array([a for a, b, n in spans]); last = np.array([b for a, b, n in spans])
    arc = np.searchsorted(first - tol, t, side="right") - 1
    if (arc < 0).any() or (t > last[arc] + tol).any():
        raise SystemExit(f"[ecef] {day}: epochs outside the arcs of the final orbit")
    # time string of every epoch is the one GROOPS wrote in the TRF orbit file; the numbers are in the TRF files
    rows = _row_strings(orb_f)
    n_fin = len(_row_strings(fin_f))
    out = ["groops instrument version=20200123", "# MISCVALUES", f"{14:11d}{len(np.unique(arc)):11d}",   # CHANGED 2026-10-14: 14 data columns
           "# " + HEADER, "# " + "=" * (len(HEADER) + 1)]
    for a in np.unique(arc):
        idx = np.where(arc == a)[0]
        out.append(f"{len(idx):11d}")
        for k in idx:
            vals = np.concatenate([pos[k], vel[k], acc[k], [U[k], lat[k], lon[k], alt[k], A_ram[k]]])   # CHANGED 2026-10-14: + A_ram
            out.append(rows[k].split()[0] + "".join(f" {v: .18e}" for v in vals))
    dst = ecef_file(run_dir, day)
    dst.write_text("\n".join(out) + "\n")
    return (f"[ecef] {day}: {len(t)} of {n_fin} final-orbit epochs, {len(np.unique(arc))} arcs ({dst})", dst)


# =====================================================================================================
# 5. comparison with astropy (standard IERS-based CRF -> ITRS) for the report
# =====================================================================================================

def compare_with_astropy(run_dir, day):
    """Max difference of GROOPS's Earth-fixed position / velocity to astropy's GCRS -> ITRS (same epochs).
    Returns a report line; any failure (astropy missing, no IERS tables) is reported, not raised."""
    try:
        import astropy.units as u
        from astropy.time import Time
        from astropy.coordinates import GCRS, ITRS, CartesianRepresentation, CartesianDifferential
        run_dir = Path(run_dir)
        kind, c = read_instrument(final.final_file(run_dir, day))               # CRF, final orbit
        kind, e = read_instrument(ecef_file(run_dir, day))                      # TRF, this module
        keep = np.isin(np.round(c[:, 0]*86400, 3), np.round(e[:, 0]*86400, 3))  # epochs present in both
        c = c[keep]
        tt = Time(np.floor(c[:, 0]), c[:, 0] - np.floor(c[:, 0]) + settings.TT_MINUS_GPS/86400.0,
                  format="mjd", scale="tt")                                     # GPS -> TT
        rep = CartesianRepresentation(c[:, 1:4].T*u.m, differentials=CartesianDifferential(c[:, 4:7].T*u.m/u.s))
        itrs = GCRS(rep, obstime=tt).transform_to(ITRS(obstime=tt))
        r = itrs.cartesian.xyz.to_value(u.m).T
        v = itrs.velocity.d_xyz.to_value(u.m/u.s).T
        dr = np.linalg.norm(r - e[:, 1:4], axis=1).max()
        dv = np.linalg.norm(v - e[:, 4:7], axis=1).max()
        return f"[ecef check] {day}: GROOPS Earth-fixed minus astropy ITRS: position max {dr:.4f} m, velocity max {dv:.6f} m/s"
    except Exception as ex:                                                     # report, never stop the run
        return f"[ecef check] {day}: astropy comparison not done ({type(ex).__name__}: {ex})"


# =====================================================================================================
# 6. all days
# =====================================================================================================

def make_ecef(run_dir, final_files, s04_text, data_dir, exe, glob_):
    """final_files: the files written by final.make_final. Returns report lines."""
    run_dir = Path(run_dir)
    days = [f.parent.name for f in final_files]
    if not days:
        return ["[ecef] no final file, nothing to do"]
    b = pod_blocks(s04_text)
    gfc_path = Path(b["gfc"].replace("{groopsDataDir}", str(Path(data_dir).resolve())))
    (run_dir / SCRIPT).write_text(script_text(s04_text, days))
    run_groops.run_scripts(run_dir, [SCRIPT], data_dir, exe, glob_)
    gfc = read_gfc(gfc_path, b["gfc_degree"])
    sat_path = Path(b["sat"].replace("{groopsDataDir}", str(Path(data_dir).resolve())))   # NEW 2026-10-14
    sat_name, sat_mass, surfaces = read_satellite_model(sat_path)                          # NEW 2026-10-14
    lines = ["[ecef] Earth-fixed file per day: position, velocity, SRP+ERP+3BP acceleration, U_grav "
             f"(GOCO06s degree {b['gfc_degree']}, {gfc_path.name})"]
    lines.append(f"[ecef] ram area from {sat_path.name}: satellite {sat_name}, mass {sat_mass:.2f} kg, "
                 f"{len(surfaces)} surfaces (C_D and mass are not in the file)")             # NEW 2026-10-14
    for d in days:
        lines.append(write_ecef(run_dir, d, gfc, surfaces)[0])                               # CHANGED 2026-10-14: + surfaces
    lines += [compare_with_astropy(run_dir, d) for d in days]
    return lines

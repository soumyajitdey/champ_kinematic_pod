"""Step 2: rough CHAMP positions from the GPS receiver data alone (reused from the old GPS-only code, 2026-10-09).

Single point positioning (SPP) with RTKLIB rnx2rtkp (open source, standard GNSS tool; Ubuntu package
"rtklib"). One position per epoch from dual-frequency, ionosphere-free GPS code observations, GPS
orbits and clocks from the SP3 files of the GPS products already used by GROOPS. No troposphere model
(LEO above the troposphere). No elevation mask: a LEO receiver also tracks satellites below its local
horizon. Broadcast navigation files of the day are needed as well (see below). Accuracy: a few meters; GROOPS only needs it as linearization point
(CORRECTED 2026-10-10, GROOPS source gnssReceiverGeneratorLowEarthOrbiter.cpp l.205-214, gnssReceiver.cpp
l.821-848: preprocessing re-estimates each epoch's position from the pseudoranges starting at the a priori position
and removes pseudoranges with residuals above codeMaxPositionDiff = 300 m (TU Graz 03groopsGnssProcessing.xml)).

Steps per day:
  1. clean_rinex: copy of the RINEX 2 file with only C1, P1, P2 (RTKLIB reads RINEX 2 observation
     types as 2 characters; the CHAMP extension types LP1/SA are not needed for SPP).
  2. rnx2rtkp in single mode, ECEF output.
  3. pos_to_sp3: solutions with fewer than MIN_SATS satellites or a standard deviation above MAX_STD
     are dropped; the rest is written as SP3 (ECEF, km), read by GROOPS Sp3Format2Orbit like any SP3 orbit.
"""
import gzip
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from core import settings                                                  # CHANGED 2026-10-10

MIN_SATS = settings.SPP_MIN_SATS   # >= 5 satellites (one more than unknowns, RAIM possible)
MAX_STD = settings.SPP_MAX_STD     # [m] largest accepted RTKLIB position standard deviation (sdx, sdy, sdz)
SAT_ID = "L06"        # satellite identifier written into the SP3 file (read by Sp3Format2Orbit)
SIGMA_MM = settings.SPP_SIGMA_MM   # NEW 2026-10-10: position standard deviation written as SP3 'EP' record [mm];
                                   # read by GROOPS Sp3Format2Orbit (outputfileCovariance) for the dynamic fit

CONF = """pos1-posmode       =single
pos1-frequency     =l1+2
pos1-soltype       =forward
pos1-elmask        =-90
pos1-dynamics      =off
pos1-tidecorr      =off
pos1-ionoopt       =dual-freq
pos1-tropopt       =off
pos1-sateph        =precise
pos1-posopt5       =on
pos1-navsys        =1
out-solformat      =xyz
out-outhead        =on
out-timesys        =gpst
out-timeform       =hms
out-timendec       =3
"""
# pos1-posopt5 = RAIM FDE (receiver autonomous integrity monitoring, fault detection and exclusion)

# Broadcast navigation files are required by RTKLIB 2.4.3 (b34) also with SP3 precise ephemeris:
# satposs() first takes each satellite clock from the broadcast ephemeris (ephclk) to compute the signal
# transmission time and skips satellites without it ("no broadcast clock"; checked with a trace).
# Satellite positions and clocks themselves then come from SP3 (pos1-sateph=precise).


def _epoch(line):
    try:
        y, mo, d, h, mi = (int(line[a:a + 2]) for a in (1, 4, 7, 10, 13))
        s = float(line[15:26])
        return datetime(2000 + y if y < 80 else 1900 + y, mo, d, h, mi) + timedelta(seconds=s), int(line[28]), int(line[29:32])
    except (ValueError, IndexError):
        return None


def clean_rinex(src, dst, keep=("C1", "P1", "P2")):
    """RINEX 2 observation file -> RINEX 2.11 file with only the types in `keep` (GPS satellites only).
    Event records (flags 2-5) are skipped; flag 1 (power failure) epochs are kept."""
    lines = Path(src).read_text(errors="replace").splitlines()
    types, i, head = [], 0, []
    while i < len(lines) and "END OF HEADER" not in lines[i]:
        label = lines[i][60:].strip()
        if label == "# / TYPES OF OBSERV":
            types += lines[i][6:60].split()
        elif label not in ("RINEX VERSION / TYPE", "# / TYPES OF OBSERV", "WAVELENGTH FACT L1/2"):
            head.append(lines[i])
        i += 1
    i += 1
    missing = [t for t in keep if t not in types]
    if missing:
        sys.exit(f"[spp] {src}: observation types {missing} not in the file (types: {types})")
    idx = [types.index(t) for t in keep]
    nl = (len(types) + 4) // 5
    out = [f"{'2.11':>9s}{'':11s}{'OBSERVATION DATA':20s}{'G (GPS)':20s}RINEX VERSION / TYPE"] + head
    out.append(f"{len(keep):6d}" + "".join(f"{t:>6s}" for t in keep) + " " * (54 - 6 * len(keep)) + "# / TYPES OF OBSERV")
    out.append(f"{'':60s}END OF HEADER")
    while i < len(lines):
        e = _epoch(lines[i])
        if e is None:
            i += 1
            continue
        t, flag, ns = e
        nsl = (ns + 11) // 12
        sats = "".join(lines[i + k][32:68] for k in range(nsl))
        i += nsl
        if flag > 1:                                       # special records follow: skip them
            while i < len(lines) and _epoch(lines[i]) is None:
                i += 1
            continue
        recs = []
        for k in range(ns):
            buf = "".join(l.ljust(80)[:80] for l in lines[i:i + nl])
            i += nl
            sid = sats[3 * k:3 * k + 3]
            if sid[0] not in " G":
                continue
            recs.append(("G" + sid[1:].replace(" ", "0"), "".join(buf[16 * j:16 * j + 16] for j in idx)))
        if not recs:
            continue
        satlist = "".join(s for s, _ in recs)
        first = (f" {t.year % 100:02d} {t.month:2d} {t.day:2d} {t.hour:2d} {t.minute:2d}"
                 f"{t.second + t.microsecond * 1e-6:11.7f}  {flag:1d}{len(recs):3d}")
        out.append(first + satlist[:36])
        for k in range(36, len(satlist), 36):
            out.append(" " * 32 + satlist[k:k + 36])
        for _, data in recs:
            out.append(data.rstrip())
    Path(dst).write_text("\n".join(out) + "\n")


def _plain(path, tmp):
    """Uncompressed copy (.gz) or the file itself; RTKLIB wants .sp3 / .eph extensions for SP3."""
    path = Path(path)
    name = path.name[:-3] if path.name.endswith(".gz") else path.name
    stem = name[:-4] if name.lower().endswith(".sp3") else name
    dst = Path(tmp) / (stem + ".sp3")
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as f, open(dst, "wb") as g:
            shutil.copyfileobj(f, g)
    else:
        shutil.copy(path, dst)
    return dst


def run_rtklib(rnx, sp3_files, nav_files, pos, exe=None):
    """rnx2rtkp single point positioning -> RTKLIB .pos file (ECEF)."""
    exe = exe or shutil.which("rnx2rtkp")
    if not exe:
        sys.exit("[spp] RTKLIB rnx2rtkp not found. Install it with:  sudo apt install rtklib")
    with tempfile.TemporaryDirectory() as tmp:
        conf = Path(tmp) / "spp.conf"
        conf.write_text(CONF)
        clean = Path(tmp) / "obs.obs"
        clean_rinex(rnx, clean)
        sp3 = [str(_plain(s, tmp)) for s in sp3_files]
        nav = []
        for f in nav_files:                                 # copies: RTKLIB unpacks .Z/.gz next to the file
            dst = Path(tmp) / Path(f).name
            shutil.copy(f, dst)
            nav.append(str(dst))
        cmd = [exe, "-k", str(conf), "-o", str(pos), str(clean)] + nav + sp3
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not Path(pos).is_file():
            sys.exit(f"[spp] rnx2rtkp failed ({r.returncode}): {r.stderr.strip()[-500:]}")


def read_pos(pos):
    """RTKLIB xyz .pos -> list of (datetime, x, y, z, Q, ns, sdx, sdy, sdz)."""
    rows = []
    for line in Path(pos).read_text().splitlines():
        if line.startswith("%") or not line.strip():
            continue
        p = line.split()
        t = datetime.strptime(p[0] + " " + p[1], "%Y/%m/%d %H:%M:%S.%f")
        rows.append((t, float(p[2]), float(p[3]), float(p[4]), int(p[5]), int(p[6]),
                     float(p[7]), float(p[8]), float(p[9])))
    return rows


def ep_record(sigma_mm):                                                  # NEW 2026-10-10
    """SP3-c 'EP' record: position standard deviations x, y, z [mm] in columns 5-8, 10-13, 15-18, clock 20-26,
    correlations xy 28-35, xz 37-44, xc 46-53, yz 55-62 (all 0). Column positions as read by GROOPS
    Sp3Format2Orbit (substr(4,4), (9,4), (14,4), (27,8), (36,8), (54,8))."""
    b = [" "] * 80
    def put(col, width, text):                       # col: 1-based first column
        t = text.rjust(width)
        b[col - 1:col - 1 + width] = list(t)
    b[0:2] = list("EP")
    for col in (5, 10, 15):
        put(col, 4, f"{int(sigma_mm)}")
    put(20, 7, "0")
    for col in (28, 37, 46, 55, 64, 73):
        put(col, 8, "0")
    return "".join(b).rstrip()


def pos_to_sp3(pos, sp3, sat=SAT_ID):
    """Accepted SPP positions -> SP3 file (ECEF, km, GPS time). Returns (accepted, total)."""
    rows = read_pos(pos)
    ok = [r for r in rows if r[5] >= MIN_SATS and max(r[6], r[7], r[8]) <= MAX_STD]
    if not ok:
        sys.exit(f"[spp] {pos}: no accepted SPP position")
    t0 = ok[0][0]
    out = [f"#cP{t0.year:4d} {t0.month:2d} {t0.day:2d} {t0.hour:2d} {t0.minute:2d} {t0.second:11.8f} {len(ok):7d} ORBIT IGS14 FIT  SPP",
           "## 0000      0.00000000    10.00000000 00000 0.0000000000000",
           f"+    1   {sat}" + "  0" * 16,
           "%c L  cc GPS ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc",
           "%c cc cc ccc ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc",
           "%f  1.2500000  1.025000000  0.00000000000  0.000000000000000",
           "%f  0.0000000  0.000000000  0.00000000000  0.000000000000000",
           "%i    0    0    0    0      0      0      0      0         0",
           "%i    0    0    0    0      0      0      0      0         0",
           "/* GPS-only single point positioning (RTKLIB rnx2rtkp), rough a priori orbit"]
    for t, x, y, z, *_ in ok:
        out.append(f"*  {t.year:4d} {t.month:2d} {t.day:2d} {t.hour:2d} {t.minute:2d} {t.second + t.microsecond * 1e-6:11.8f}")
        out.append(f"P{sat}{x / 1e3:14.6f}{y / 1e3:14.6f}{z / 1e3:14.6f}{999999.999999:14.6f}")
        out.append(ep_record(SIGMA_MM))                                     # NEW 2026-10-10
    out.append("EOF")
    Path(sp3).write_text("\n".join(out) + "\n")
    return len(ok), len(rows)


def make_spp_sp3(rnx, sp3_files, nav_files, out_sp3):
    """RINEX (one day) + GPS SP3 files + broadcast navigation files -> SPP orbit as SP3.
    CHANGED 2026-10-10: always computed new inside the run folder (no reuse of earlier files).
    Returns (accepted epochs, total epochs)."""
    out_sp3 = Path(out_sp3)
    pos = out_sp3.with_suffix(".pos")
    print(f"[spp] RTKLIB single point positioning: {Path(rnx).name}")
    run_rtklib(rnx, sp3_files, nav_files, pos)
    n_ok, n = pos_to_sp3(pos, out_sp3)
    print(f"[spp] {out_sp3.name}: {n_ok} of {n} epochs accepted (>= {MIN_SATS} satellites, std <= {MAX_STD} m)")
    return n_ok, n

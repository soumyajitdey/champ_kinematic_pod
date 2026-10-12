"""GPS orbit/clock/attitude/bias products for the GROOPS scripts and RTKLIB.

--products repro3 (default): TU Graz IGS repro3 (TUG0R03FIN), the product set the TU Graz scripts are written
    for (orbits 5 min, clocks 30 s, attitude 30 s, code+phase signal biases). Provided BY HAND (confirmed
    2026-10-10): the four TU Graz repository zip files (DOI 10.3217/dataset-4528-0723-0867) in
    work/downloads/repro3/. The needed daily files are extracted from them. Daily files already present in
    work/inputs/igs_repro3/ are used as they are.
--products final: IGS final orbits + 30-s clocks (downloaded with core/legacy_download.py, as in the old code).
    No GPS attitude, no signal biases.
--products ultra: IGS ultra-rapid (iguWWWWD_00.sp3 of the next day: observed half covers the day), orbits and
    clocks at 15-min sampling (IGS products page). No GPS attitude, no signal biases.
Reused from the old code (core/gnss_products.py); CHANGED: repro3 only from the local zips (no CDDIS / no
HTTP range requests), missing zips are listed by missing_by_hand().
"""
import gzip
import sys
import zipfile
from datetime import date
from pathlib import Path

from core import settings

REPRO3_KINDS = {   # file name part -> TU Graz repository zip (download by hand)
    "01D_05M_ORB.SP3": "https://repository.tugraz.at/records/ebamh-r3860/files/TUG0R03FIN_1994-2020_01D_05M_ORB.SP3.zip?download=1",
    "01D_30S_CLK.CLK": "https://repository.tugraz.at/records/4r4fn-bx093/files/TUG0R03FIN_1994-2020_01D_30S_CLK.CLK.zip?download=1",
    "01D_30S_ATT.OBX": "https://repository.tugraz.at/records/hrm5k-3nf90/files/TUG0R03FIN_1994-2020_01D_30S_ATT.OBX.zip?download=1",
    "01D_01D_OSB.BIA": "https://repository.tugraz.at/records/xxr3e-tgt91/files/TUG0R03FIN_1994-2020_01D_01D_OSB.BIA.zip?download=1",
}


def ydoy(d):
    return f"{d.year}{d.timetuple().tm_yday:03d}"


def product_dir(kind):
    return settings.INPUTS / f"igs_{kind}"


def _zip_path(kind):
    return settings.REPRO3_LOCAL / Path(REPRO3_KINDS[kind].split("?")[0]).name


def _daily_name(kind, d):
    return f"TUG0R03FIN_{ydoy(d)}0000_{kind}.gz"


def missing_by_hand(products, days):
    """Lines describing every missing by-hand GPS product file (empty list: nothing missing)."""
    if products != "repro3":
        return []
    out = []
    for kind in REPRO3_KINDS:
        have_daily = all((product_dir("repro3") / _daily_name(kind, date.fromisoformat(d))).is_file() for d in days)
        if not have_daily and not _zip_path(kind).is_file():
            out.append(f"{_zip_path(kind)}\n      download: {REPRO3_KINDS[kind]}")
    return out


_ZIPS = {}


def _repro3_day(d, dest):
    for kind in REPRO3_KINDS:
        out = Path(dest) / _daily_name(kind, d)
        if out.is_file():
            continue
        if kind not in _ZIPS:
            print(f"[products] reading {_zip_path(kind)}")
            _ZIPS[kind] = zipfile.ZipFile(_zip_path(kind))
        stem = f"TUG0R03FIN_{ydoy(d)}0000_{kind}"
        hit = [n for n in _ZIPS[kind].namelist() if Path(n).name.startswith(stem)]
        if not hit:
            sys.exit(f"[products] {stem} not in {_zip_path(kind)}")
        data = _ZIPS[kind].read(hit[0])
        out.write_bytes(data if data[:2] == b"\x1f\x8b" else gzip.compress(data))
        print(f"[products] {out.name} extracted from {_zip_path(kind).name}")


def _final_day(d, dest):
    from core import legacy_download as L
    names = {"sp3": f"IGS0FIN_{ydoy(d)}_ORB.SP3", "clk_30s": f"IGS0FIN_{ydoy(d)}_CLK.CLK"}
    if all((Path(dest) / n).is_file() for n in names.values()):
        return
    cache = settings.DOWNLOADS / "gnss" / "igs_final"
    cache.mkdir(parents=True, exist_ok=True)
    rep = L.Report()
    paths = L.fetch_igs(d, str(cache), rep)
    for k, n in names.items():
        if k not in paths:
            sys.exit(f"[products] IGS final {k} for {d} failed: " + "; ".join(r[3] for r in rep.failed()))
        (Path(dest) / n).write_bytes(Path(paths[k]).read_bytes())


def _ultra_day(d, dest):
    from core import legacy_download as L
    out = Path(dest) / f"IGU_{ydoy(d)}_ORB.SP3"
    if out.is_file():
        return
    cache = settings.DOWNLOADS / "gnss" / "igs_ultra"
    cache.mkdir(parents=True, exist_ok=True)
    rep = L.Report()
    p = L.fetch_igu(d, str(cache), rep)
    if not p:
        sys.exit(f"[products] IGS ultra-rapid for {d} failed: " + "; ".join(r[3] for r in rep.failed()))
    out.write_bytes(Path(p).read_bytes())


def get_products(kind, days):
    """Place the GPS products of the days into work/inputs/igs_<kind> (folder `igs` of the run)."""
    dest = product_dir(kind)
    dest.mkdir(parents=True, exist_ok=True)
    fn = {"repro3": _repro3_day, "final": _final_day, "ultra": _ultra_day}[kind]
    for day in days:
        fn(date.fromisoformat(day), dest)
    return dest


def sp3_files(kind, days):
    """GPS SP3 files (orbits + clocks) of the days, for RTKLIB."""
    d = product_dir(kind)
    names = {"repro3": lambda x: _daily_name("01D_05M_ORB.SP3", x),
             "final": lambda x: f"IGS0FIN_{ydoy(x)}_ORB.SP3",
             "ultra": lambda x: f"IGU_{ydoy(x)}_ORB.SP3"}[kind]
    files = [d / names(date.fromisoformat(day)) for day in days]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        sys.exit("[products] SP3 files missing:\n  " + "\n  ".join(missing))
    return files

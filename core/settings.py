"""Settings of the CHAMP GPS-only kinematic PPP pipeline (pipeline confirmed 2026-10-10).

No CHAMP RSO (or any other external CHAMP orbit) is downloaded or read anywhere in this package.
"""
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"                       # downloads, inputs, GROOPS data, results
RESULTS = WORK / "results"                 # one new folder per run, nothing is overwritten
INPUTS = WORK / "inputs"
DOWNLOADS = WORK / "downloads"

# ---------------- period (confirmed: 2010-05-01 .. 2010-05-02, both days included) ----------------
# Processed with TU Graz's daily loop (CHANGED 2026-10-11): each day uses only its own input files.
START, END = "2010-05-01", "2010-05-02"
DAYS = [str(date.fromisoformat(START) + timedelta(days=k))
        for k in range((date.fromisoformat(END) - date.fromisoformat(START)).days + 1)]
MJD0 = date(1858, 11, 17)
TIME_START = (date.fromisoformat(START) - MJD0).days      # MJD of START 00:00 (GPS time)
TIME_END = TIME_START + len(DAYS)                         # MJD of END+1 00:00 (exclusive)

# ---------------- satellite ----------------
NAME = "CHAMP"
SATELLITE = "champ"          # TU Graz GROOPS metadata name (gnss/receiverLowEarthOrbiter/champ, satelliteModel)

# ---------------- GROOPS (confirmed: reuse the existing build in ~/groops_build) ----------------
GROOPS_TAG = "2025-11-15"
GROOPS_EXE = Path.home() / "groops_build" / "groops_install" / "bin" / "groops"

# ---------------- TU Graz server (GROOPS data + scenario scripts + published CHAMP orbits) ----------------
TUG_BASES = [
    "https://ftp.tugraz.at/outgoing/ITSG/groops",
    "https://ftp.tugraz.at/pub/ITSG/groops",
]
DATA_ZIP = "data.zip"
SCENARIOS = {
    "kinematic": {"zip": "scenario/scenarioLeoKinematicOrbit.zip", "dir": "scenarioLeoKinematicOrbit"},
    "reducedDynamic": {"zip": "scenario/scenarioLeoReducedDynamicOrbit.zip", "dir": "scenarioLeoReducedDynamicOrbit"},
    "gnssPPP": {"zip": "scenario/scenarioGnssPPP.zip", "dir": None},   # NEW 2026-10-11: SLR validation only
}                                                                   #   (TU Graz station tide/loading settings)
TUG_ORBITS = ("https://ftp.tugraz.at/pub/ITSG/satelliteOrbitProducts/operational/CHAMP/{kind}/{year}/"
              "CHAMP_{kind}_{day}.txt.gz")                 # validation only

# ---------------- GPS products ----------------
PRODUCTS = ["repro3", "final", "ultra"]                   # confirmed: repro3 default
REPRO3_LOCAL = DOWNLOADS / "repro3"                       # by hand: the four TU Graz repro3 zip files

# ---------------- RTKLIB rough positions (confirmed item D, unchanged from the old GPS-only code) ----------------
SPP_MIN_SATS = 5
SPP_MAX_STD = 30.0           # [m]

# ---------------- a priori orbit (confirmed items 1-9) ----------------
START_ORBITS = ["polynomial", "dynamic"]
POLY_DEGREE = 5              # polynomial option: degree of the least squares polynomial
POLY_WINDOW = 120            # [s] all rough positions within +-120 s of the epoch are used (>= degree+1 needed)
POLY_EXTRAPOLATION = 60      # [s] one-sided data (start/end of data): nearest rough position within 60 s
VELOCITY_DEGREE = 8          # degree of the polynomial for the velocities (OrbitAddVelocityAndAcceleration)
DYN_SAMPLING = 10            # [s] grid of the dynamic fit (CHAMP GPS data sampling)
DYN_MAX_GAP = 45             # [s] grid steps up to 40 s (= up to 30 s missing data) are filled; 45 not 40 because a
                             #     40-s step computed from MJD times can exceed 40 s by rounding (tested 2026-10-09)
DYN_FILL_DEGREE = 5          # polynomial degree of that gap filling (old code)
DYN_FILL_SPAN = 60           # [s] data used on each side of a filled gap (old code)
DYN_MAX_ARC_EPOCHS = 8640    # 24 h at 10 s
DYN_MIN_ARC_EPOCHS = 10      # Claude's choice (implementation): the orbit integration (integrationDegree 7) needs
                             #     at least 8 epochs per arc; shorter data islands get no a priori position
SPP_SIGMA_MM = 3000          # [mm] uncertainty of each rough position in the dynamic fit (3 m)

# ---------------- SLR validation (NEW 2026-10-11, confirmed items 4-16, A, B; validation only) ----------------
# SLR data are used ONLY in the validation step (step 10); no processing step reads them.
SLR_NP_URL = "https://edc.dgfi.tum.de/pub/slr/data/npt/champ/{y}/champ.{ymd}"   # ILRS EDC, CSTG normal points
SLR_LRR = (0.0, 0.0, 0.250)    # [m] retroreflector reference point in the satellite frame (z to nadir): nominal 250 mm
                               #     from the centre of mass toward nadir (Neubert, Grunwaldt & Neubert, "The
                               #     Retro-Reflector for the CHAMP Satellite: Final Design and Realization"; item 6)
SLR_IDS = {"cospar": "0003902", "norad": "26405", "sic": "8002"}               # ILRS CHAMP mission page
SLR_ELEVATION_CUTOFF = 5       # [deg] GROOPS default (item 12)
SLR_INTERPOLATION_DEGREE = 7   # orbit interpolation to the SLR epochs: 8 nearest orbit points (GROOPS default)
SLR_SCREEN_RESIDUAL = 0.150    # [m] screened table: |residual| > 15 cm removed (Strugarek et al. 2022, GPS Solut 26:104)
SLR_SCREEN_STATION_STD = 0.050 # [m] screened table: station-days with std > 5 cm removed (Strugarek et al. 2022)

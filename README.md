# CHAMP orbit from its own GPS data only — kinematic PPP + reduced-dynamic POD (GROOPS + RTKLIB)

Pipeline confirmed in chat on 2026-10-10; reduced-dynamic POD (steps 7-8) confirmed 2026-10-11 ("version 2",
one process, results in one folder). **No CHAMP RSO and no other external CHAMP orbit is downloaded or read
at any step.** The RSO download function of the old download module was removed. TU Graz's published CHAMP orbits
and the SLR data are downloaded only for the validation in steps 9-10, never used in the processing.

## Flowchart

```
 INPUTS
 ------
 Downloaded by the script:                      Provided by you (by hand):
   - CHAMP RINEX (GPS measurements), GFZ          - GPS broadcast navigation files (brdc), CDDIS
   - CHAMP ACC (attitude), GFZ                    - TUG repro3 GPS products (4 zip files)
   - GROOPS data + TU Graz scripts
   - TU Graz CHAMP orbits (comparison only)
                 |
 STEP 1  check inputs: missing by-hand files -> stop and list them with their paths
                 |
 STEP 2  RTKLIB: rough CHAMP position per epoch (pseudoranges only, metres)
                 |
 STEP 3  GROOPS 01: GPS products (orbits, clocks, attitude, biases)
                 |
 STEP 4  GROOPS 02: CHAMP RINEX + attitude + rough positions
                 |
 STEP 5  GROOPS 02b: a priori orbit   --start-orbit polynomial | dynamic
         + TU Graz's synchronization: GPS observations, a priori orbit, attitude with identical epochs
                 |
 STEP 6  GROOPS 03: kinematic PPP (pseudoranges + carrier phases -> position per epoch)
                 |
 STEP 7  GROOPS 04: force-model orbit (gravity, tides, drag JB2008, solar + Earth radiation, relativity,
         20-min stochastic pulses) fitted to the kinematic positions with their 3x3 covariances
         = a priori orbit of step 8                     (TU Graz reduced-dynamic 03groopsVariational.xml)
                 |
 STEP 8  GROOPS 05: reduced-dynamic POD: initial state per arc + stochastic pulses estimated from the CHAMP GPS
         pseudoranges and carrier phases (integer ambiguities)  (TU Graz reduced-dynamic 04groopsGnssProcessing.xml)
                 |
 STEP 9  comparison of BOTH orbits (kinematic, reduced-dynamic) with BOTH TU Graz CHAMP orbits (plots, RMS R/T/N)
                 |
 STEP 10 SLR validation: measured minus computed laser range at the SLR normal points, for our two orbits and
         TU Graz's two orbits (GROOPS SlrProcessing, nothing estimated)          (VALIDATION ONLY)
         Steps 9-10 = run_validation.py (also runs alone on a finished run folder)
                 |
 STEP 11 report.txt: settings, check numbers, comparison, exact files used, limitations

 After steps 9-10, before the report (NEW 2026-10-13): Earth-fixed file per day, GROOPS script 06 + Python
 (core/ecef_terms.py). A failure there is written to the report and stops the run only after the report is written.
```

## Run (Ubuntu / WSL, inside this folder)

```
sudo apt install rtklib                                   # once (RTKLIB rnx2rtkp)
python3 run_pipeline.py                                   # a priori option polynomial (default)
python3 run_pipeline.py --start-orbit dynamic             # a priori option dynamic
```
Options: `--products repro3|final|ultra` (default repro3), `--groops-bin /path/to/groops`

Validation only (steps 9-10) of a finished run, without rerunning the orbit processing:
```
python3 run_validation.py --run-dir work/results/<run folder>
```
Results go to a new folder `<run folder>/validation_<YYYYmmdd_HHMMSS>/` with `validation_report.txt`.
(default: your existing build `~/groops_build/groops_install/bin/groops`; this package does not build GROOPS).
Period: `START, END` in `core/settings.py` (2010-05-01 .. 2010-05-02).

**First run** creates the folders and stops with the exact list of files to copy in by hand:
- `work/inputs/brdc/brdc<doy>0.<yy>n.Z` per day (CDDIS URL printed),
- `work/downloads/repro3/TUG0R03FIN_1994-2020_*.zip` (the four TU Graz repository zips; URLs printed).
  Instead of the zips, the daily files `TUG0R03FIN_<yyyyddd>0000_<kind>.gz` can be placed in `work/inputs/igs_repro3/`.

Everything else is downloaded by the script (GFZ ISDC, TU Graz server). Existing files are kept.

## Output

`work/results/CHAMP_<start>_<end>_<receiver interval>_<products>_<start-orbit>_<YYYYmmdd_HHMMSS>/` (new folder every run, nothing overwritten; the interval is read from the INTERVAL line of the RINEX header, "NAs" if that line is missing):
- `output/<day>/champ_orbit_<day>.txt` — kinematic orbit, one file per day, and its 3x3 covariances
- `output/<day>/reducedDynamic/champ_orbit_<day>.txt` — reduced-dynamic orbit (positions + velocities, 10 s), per day
- `final/<day>/champ_orbit_reducedDynamic_<day>.txt` — **final product** (NEW 2026-10-12): the reduced-dynamic orbit
  without the first and last 3 h of the whole period (end effects; `FINAL_TRIM_HOURS` in `core/settings.py`). Written
  after all calculations; epoch lines and arcs copied unchanged. The validation (plots, tables) reads the
  reduced-dynamic orbit from here. The kinematic orbit and GROOPS's files in `output/` are not trimmed.
- `final/<day>/champ_ecef_<day>.txt` — **Earth-fixed file** (NEW 2026-10-13), same epochs and arcs as the final
  orbit: MJD (GPS) | x y z [m] | vx vy vz [m/s] | ax ay az [m/s^2] | U_grav [m^2/s^2] | lat lon [deg] alt [km] (WGS84). See "Earth-fixed file" below.
- `ecef/` — intermediate GROOPS files of script 06; `06groopsEcefTerms.xml` — the executed script
- `validation/kinematic_minus_TUG_*.png`, `validation/reducedDynamic_minus_TUG_*.png` — differences vs both TU Graz
  orbits, radial / along-track / cross-track (4 plots); in the reducedDynamic plots, dashed lines mark the start of each reduced-dynamic arc
- `report.txt` — check numbers, RMS tables, TU Graz scenario zip checksums, **exact files used**, limitations
- `validation/slr_residuals.png`, SLR tables in `report.txt` — SLR residuals of the four orbits
- `log/` — GROOPS log of each script; the executed XML scripts are in the run folder
- `data/<day>/champReducedDynamic/` — intermediate CHAMP files of steps 7-8 (nothing of steps 3-6 is overwritten)

## Earth-fixed file (NEW 2026-10-13, user decisions: Earth-fixed frame, all terms in the same frame)

`final/<day>/champ_ecef_<day>.txt` (GROOPS instrument text layout, type MISCVALUES with 13 data columns; arc blocks as in
the final orbit file, so the same reader works). The CRF files in `final/` are unchanged.

| column | content | how |
|---|---|---|
| 0 | MJD, GPS time | as in the final orbit file |
| 1-3 | position x y z [m], TRF | `Orbit2EarthFixedOrbit` |
| 4-6 | velocity [m/s], TRF | same program: v = R v - omega x r (velocity in the rotating frame) |
| 7-9 | acceleration SRP + ERP + 3BP [m/s^2], TRF | `SimulateAccelerometer` (satellite frame) -> `InstrumentRotate` with the star camera (-> CRF) -> `InstrumentRotate` with `InstrumentEarthRotation` (-> TRF, pure rotation) |
| 10 | U_grav [m^2/s^2] = -V | Python, GOCO06s file and maximum degree read from script 04 (120), at the TRF positions; static field, no tides |
| 11-13 | latitude [deg], longitude [deg], altitude [km] | Python, WGS84 ellipsoid (a = 6378137 m, 1/f = 298.257223563), from the TRF positions; geodetic latitude, ellipsoidal height |

- SRP + ERP = the `radiationPressure` block of script 04 (solar flux 1367, conical eclipse, CERES albedo and longwave
  climatology, factors 1.0; includes the satellite's own thermal radiation). 3BP = the `astronomicalTide` block of script 04
  with `usePlanets` 0 (Sun and Moon; `useEarth` has no effect with Earth-centred ephemerides, tidesAstronomical.cpp).
  Satellite model, ephemerides and `earthRotation` are copied from the executed script 04, not typed again.
- One frame: all three rotations CRF -> TRF use the same `earthRotation` block as the POD. `Orbit2EarthFixedOrbit` would add
  a CM -> CE degree-1 correction by default; it is set to zero (`factor` 0), so the origin stays the centre of mass.
- Acceleration: pure rotation. `Orbit2EarthFixedOrbit` is not used for it (with an acceleration present it also subtracts
  centrifugal and Coriolis terms, orbit2EarthFixedOrbit.cpp).
- `InstrumentRotate`: `inverseRotate` 0 rotates with the stored rotation as it is (satellite -> CRF for the star camera
  file, CRF -> TRF for the Earth rotation file); the default 1 does the opposite. Checked here (see Tests).
- GROOPS forces are computed per epoch, so script 06 works on one arc; the arcs of the final orbit are restored in Python.
  Epochs without an attitude epoch are dropped by InstrumentSynchronize; the report lists "N of M" epochs per day.
- The report adds one line per day: GROOPS Earth-fixed position / velocity minus astropy GCRS -> ITRS (same epochs).
  Not a pass/fail test; the two use different EOP handling (astropy: IERS tables, no sub-daily EOP model).

## Per-step checks (run stops with a message if a number is zero)

| check | number |
|---|---|
| 2 | RTKLIB positions accepted per day (>= 5 satellites, std <= 30 m) |
| 5 | epochs with an a priori position, per day (after TU Graz's synchronization) |
| 6 | kinematic positions, per day |
| 7 | epochs with a reduced-dynamic a priori position, per day (after TU Graz's synchronization) |
| 8 | reduced-dynamic positions, per day |
| 9 | epochs compared, for each (orbit, TU Graz orbit) pair |
| 10 | SLR normal points common to all four orbits |

## Settings (confirmed 2026-10-10)

RTKLIB (step 2, from the old GPS-only code): ionosphere-free dual-frequency pseudoranges, GPS SP3 orbits/clocks +
broadcast navigation, no elevation mask, no troposphere, RAIM on, accept >= 5 satellites and std <= 30 m.

`--start-orbit polynomial`: least squares polynomial of degree 5 through all rough positions within ±120 s of each
receiver epoch (>= 6 needed; at the start/end of the data, one-sided only if the nearest is within 60 s);
velocities from a degree-8 polynomial. No arcs.

`--start-orbit dynamic`: TU Graz reduced-dynamic script `03groopsVariational.xml` (force models, 20-min stochastic
pulses, iterations unchanged) fitted to the rough positions (uncertainty 3 m each); 10-s grid with gaps of up to
30 s filled by polynomial; new arc at longer gaps and after 24 h; the fitted orbit is interpolated to the receiver
epochs with TU Graz's original resampling of script 02.

## Changes to TU Graz's scripts (GRACE-FO -> CHAMP; calculations untouched)

| script | change | from |
|---|---|---|
| all | `gracefo1`/`gracefo` -> `champ`; **TU Graz's daily loop unchanged**: each day reads only its own files | 2026-10-11 |
| 01 | final/ultra only: product file names, GPS attitude and biases off | old code |
| 02 | RINEX = GFZ CH-OG-1-SST + type mapping (Köhler 2001); GraceL1b2StarCamera -> Champ2AccStar | old code |
| 02 | GraceL1b2Orbit -> Sp3Format2Orbit of the RTKLIB rough positions | old GPS-only code |
| 02 | polynomial: orbit resampling = least squares polynomial + velocities; dynamic: resampling moved to 02b | confirmed |
| 02 | dynamic only: TU Graz's InstrumentSynchronize moved (unchanged) to the end of 02b | 2026-10-11 |
| 02b | new script (see options above) + text copy of the a priori orbit for check 5 | see below |
| 03 | `wavelengthFactor` 0.5 -> 1 (CHAMP RINEX header); final/ultra: float ambiguities | old code |
| 04 (TU Graz RD 03) | observations of the orbit fit = kinematic positions of step 6 + their 3x3 covariances (GRACE-FO: GNV1B orbit); integration on a 10-s grid in arcs (see decision 8); fitted orbit -> receiver epochs with TU Graz's original resampling of script 02, then TU Graz's synchronization of script 02 | 2026-10-11 |
| 05 (TU Graz RD 04) | same CHAMP changes as 03; CHAMP files from `data/<day>/champReducedDynamic/`, outputs to `output/<day>/reducedDynamic/` | 2026-10-11 |

## Implementation decisions made while coding (user instruction 2026-10-10: standard, physically sound, no further questions)

1. **Synchronization (CHANGED 2026-10-11).** GROOPS requires identical epochs in the a priori orbit and attitude
   files of a LEO receiver; otherwise the whole receiver is disabled (`gnssReceiverGeneratorLowEarthOrbiter.cpp`
   l.139-141). TU Graz's script 02 already ends with `InstrumentSynchronize` of GPS observations, a priori orbit and
   attitude; the package's own extra synchronization was removed. In the dynamic option, TU Graz's program runs,
   unchanged, at the end of 02b, after the fitted orbit exists.
2. **3 m uncertainty of the rough positions** is passed to GROOPS as SP3 `EP` records (standard SP3-c accuracy
   record), read by `Sp3Format2Orbit` (`outputfileCovariance`). Note: the stochastic pulses in
   `PreprocessingVariationalEquationOrbitFit` are not constrained, so one equal uncertainty for all positions scales
   only the reported a-posteriori sigma; it does not change the fitted orbit.
3. **Dynamic option, minimum arc length 10 epochs (100 s).** The orbit integration uses a degree-7 polynomial
   (GROOPS default `integrationDegree`), so at least 8 epochs per arc are needed. Shorter data islands get no
   a priori position (same effect as an epoch without rough positions).
4. **RTKLIB rough positions are recomputed in every run** (in the run folder), so a run never reuses positions
   computed with other GPS products.
5. **All fits of the TU Graz variational script** (if it contains more than one) use the rough positions as
   observations; the fitted orbit of the last fit is the a priori orbit.
6. **repro3 products only from your local zips or daily files** (no CDDIS / remote attempts), as confirmed.
7. (removed 2026-10-11: joining of daily files no longer exists; TU Graz daily loop.)
8. **Reduced-dynamic: arcs (2026-10-11; gap limit CHANGED 2026-10-11 late, user decision).** GROOPS integrates the
   variational equations with a constant step per arc (`preprocessingVariationalEquation.cpp`:
   `deltaT = T/(epochCount-1)`), so the starting orbit of each arc must have equally spaced epochs. Kinematic
   positions -> 10-s grid; gaps of up to 5 min missing data are bridged in this STARTING orbit by a degree-11 least
   squares polynomial through 15 min of kinematic positions on each side (GROOPS fillGapsLeastSquaresPolynomialFit);
   attitude linearly. Longer gaps start a new arc; arcs end at midnight (TU Graz daily loop), so no arc is longer
   than 24 h (user limit: 30 h). A dynamic orbit is continuous across data gaps (Wu et al. 1991; Selvan et al. 2023),
   so short gaps are no reason for a new arc. The fit itself uses only real kinematic positions; filled values are
   never data. Test on a simulated orbit (2 days, 2 cm noise, gaps 25 s/2/4.5/5/6/15 min, three 1-m outliers): gaps
   up to 5 min bridged, 6 and 15 min started new arcs (3 arcs per day); fitted orbit vs truth 3D RMS 0.3 cm, max
   1.0 cm, max 0.6 cm inside bridged gaps. The report lists arcs per day, their lengths and the gaps between them
   (check 8). Overlapping arcs across midnight were not adopted (decision 2026-10-11): GROOPS reads one constant
   GPS signal-bias set per run (`gnssParametrizationSignalBiases.cpp`), so neighbouring-day hours would use wrong
   biases.
9. **Reduced-dynamic: weights (2026-10-11).** The orbit fit (step 7) weights each kinematic position with its 3x3
   covariance from step 6 (GROOPS `inputfileCovariancePodEpoch`, documented input of
   `PreprocessingVariationalEquationOrbitFit`); outliers are downweighted by GROOPS's Huber method (built in).
10. **Reduced-dynamic: receiver epochs (2026-10-11).** GROOPS `leoDynamicOrbits` stops with "no variational arc
   found" if a usable GPS epoch lies outside all arcs (`variationalEquationFromFile.cpp`, `getArc`). TU Graz's
   resampling (polynomial, 300 s range, 100 s extrapolation) can place a priori positions in gaps between arcs.
   Therefore the GPS observations, the a priori orbit and the attitude are split into the arcs of the fitted orbit
   (`InstrumentSynchronize`, `irregularData`: "data outside the defined arcs will be deleted") before TU Graz's
   own synchronization.
11. **Reduced-dynamic: GPS observations (2026-10-11)** = the receiver file of the kinematic run after TU Graz's
   synchronization of step 5 (copied into `champReducedDynamic/`). Epochs without an RTKLIB rough position were
   removed there and are not used in step 8 either.
12. **Stochastic pulses** in data gaps between arcs have no observations; GROOPS regularizes such unused
   parameters (`preprocessingVariationalEquationOrbitFit.cpp`: `N(i,i)=1` if zero;
   `gnssProcessingStep.cpp`: `regularizeNotUsedParameters`). A pulse close to an arc end is determined by few
   epochs.

## Day-by-day processing (CHANGED 2026-10-11)

The first real run (polynomial option, 2010-05-01/02) agreed with TU Graz's orbits at the few-cm level on
2010-05-02 but showed decimetre drifts and jumps on 2010-05-01. Cause: the previous code ran both days in one GROOPS
loop with ONE GPS signal-bias file (the middle day, 2010-05-02). The TUG repro3 L1W phase biases of the two days
differ by 0.05-0.46 L1 cycles between satellites (e.g. G03: -0.2762 ns vs 0.0156 ns; files
`TUG0R03FIN_2010121/122..._OSB.BIA`, each valid for one day), so the integer ambiguities of day 1 were fixed with
wrong biases. The pipeline now keeps TU Graz's own daily loop (all four TU Graz scripts loop day by day and read only
that day's files, checked in the scripts): each day uses its own orbits, clocks, GPS attitude and biases.
Effects: carrier-phase ambiguities restart at midnight (as in TU Graz's own processing); polynomial option: each
day's a priori orbit uses only that day's rough positions; dynamic option: arcs end at midnight.
RTKLIB (rough positions only) still receives the GPS SP3 files of all days and selects epochs by time (GPS orbits
are continuous across midnight); no bias files are involved there.

## Behaviour of the two a priori options (measured in the synthetic test below)

| | polynomial | dynamic |
|---|---|---|
| a priori error, typical (median 3D) | 1.4 m | 0.4 m (3D RMS 42 cm) |
| epochs inside multi-minute gaps of the rough positions | some epochs get a position from a sparse or one-sided polynomial: errors up to several km (27 of 17225 epochs in the test) | no a priori position (gap > 30 s) |
| epochs with an a priori position (test) | 17225 | 17200 |

Correction of an earlier explanation (checked in GROOPS source, `polynomial.cpp` l.113-122): the 60-s one-sided
limit of the polynomial option applies at every edge of a gap in the rough positions, not only at the start and end
of the data. Correction 2 (`gnssReceiverGeneratorLowEarthOrbiter.cpp` l.205-214, `gnssReceiver.cpp` l.821-848):
GROOPS first re-estimates each epoch's position from the pseudoranges alone, starting from the a priori position,
and removes pseudoranges whose residual at that code-only position exceeds `codeMaxPositionDiff` (300 m); it does not
compare the a priori position directly with 300 m. The kinematic positions are then iterated (to 1 cm). The
km-level a priori errors of the polynomial option inside gaps are therefore expected to be removed by this
re-estimation; this has not been verified with real data.

## SLR validation (step 10, NEW 2026-10-11; confirmed items 4-16, A, B)

SLR data are used only here. `core/slr.py: check_isolation()` stops the run if a processing script (01-05) refers
to SLR data.

- Residual = measured one-way laser range - range computed from the orbit (GROOPS `SlrProcessing`, no parameter
  estimated). The computed range includes: orbit interpolated to the SLR epoch with a degree-7 polynomial through the
  8 nearest orbit points (GROOPS default; a two-point linear interpolation would be wrong by up to ~110 m at 10 s
  spacing), retroreflector offset rotated with the CHAMP attitude, light travel time, station coordinates SLRF2020
  (centre-of-mass frame), station tides/loading with TU Graz's settings (copied unchanged from their GNSS PPP
  scenario), Mendes-Pavlis troposphere with the meteorological data of the normal points, Shapiro delay.
- Not applied: ILRS station range/time biases. GROOPS documentation (`slrParametrizationRangeBiasStationApriori.h`,
  `slrParametrizationTimeBiasApriori.h`): determined with passive satellites (LAGEOS, Etalon), not suitable for
  active ones.
- Data: ILRS EDC CSTG normal points `edc.dgfi.tum.de/pub/slr/data/npt/champ/<year>/champ.<yyyymmdd>` for the days
  START-1 .. END+1 (passes near midnight); a normal point counts on the day of its epoch. Converted with GROOPS
  `Cstg2NormalPoints` (UTC -> GPS time, two-way -> one-way). Station files downloaded one by one from the GROOPS data
  folder on the TU Graz server (no data.zip needed). Stations without SLRF2020 coordinates are not used.
- CHAMP retroreflector: nominal reference point 250 mm from the centre of mass toward nadir, (0, 0, +0.250) m in the
  satellite frame, no extra range correction (Neubert, Grunwaldt & Neubert, CHAMP retroreflector design paper;
  item 6). Identifiers COSPAR 0003902, NORAD 26405, SIC 8002 (ILRS CHAMP page). Platform file made with GROOPS
  `PlatformCreate`.
- Orbits: our kinematic and reduced-dynamic, TU Graz's kinematic and reduced-dynamic (converted to a GROOPS-readable
  file if needed). Attitude: our CHAMP star camera data, resampled to each orbit's epochs with TU Graz's own
  resampling program of script 02. Earth rotation: same TU Graz element as the orbit processing (script 03).
- Elevation cut-off 5° (GROOPS default). GROOPS's default gross-error limit of 30 m is kept.
- Tables: (a) all residuals; (b) screened as in Strugarek et al. 2022 (GPS Solut 26:104): |residual| > 15 cm
  removed, then station-days with standard deviation > 5 cm removed. Both on the normal points common to all orbits.
- Tested here with synthetic data (GROOPS-simulated orbit, synthetic CSTG files for 3 stations): a 10.0 cm range
  offset appears as +10.00 cm in every residual (spread < 0.06 mm); injected orbit errors appear in the residual
  differences (2 cm noise -> 2.1 cm; 1 cm -> 0.9 cm). Not tested here: real EDC files, real station files, TU Graz's
  PPP settings (server not reachable from the build machine).

## Tests (2026-10-13, Earth-fixed file)

- Done here (GROOPS 2025-11-15, synthetic test orbit, 2 days, `earthRotation` gmst because the EOP file is not here, constant
  satellite-frame acceleration instead of SimulateAccelerometer):
  - `InstrumentRotate` (inverseRotate 0) with the star camera file = quaternion matrix R a (difference 0 to 1e-21 m/s^2);
    with the Earth rotation file = `Orbit2EarthFixedOrbit` position (2e-9 m).
  - Whole chain acceleration: Python R_z(theta) R_q a minus GROOPS output: 8e-21 m/s^2.
  - `Orbit2EarthFixedOrbit` with the default gravityfield and with factor 0 gave identical positions here.
  - U_grav (test field J2..J6): independent Legendre sum minus Python: 1.5e-8 m^2/s^2. Earlier test of `U_grav_full`: 7e-8 J/kg
    against a reference implementation.
  - Output file: arcs identical to the final orbit file, times identical, read back by GROOPS.
  - XML of script 06 generated from the executed script 04 (cmp/.../04groopsVariational.xml); the blocks copied from it are
    valid in `forces` of PreprocessingVariationalEquation, the same type as in SimulateAccelerometer.
- NOT tested here: `SimulateAccelerometer` itself (needs the JPL DE432, EOP, CERES and CHAMP satellite model files, which
  are only in your groopsData folder), the values of SRP / ERP / 3BP, the real `earthRotation` (EOP file), GOCO06s itself,
  the astropy comparison on real data.

## Tests (2026-10-11, reduced-dynamic version)

- Not run with GROOPS here (user decision 2026-10-11).
- Done here: Python compile check; script generation from the user's TU Graz scripts (kinematic 01/02/03,
  reduced-dynamic 03/04) for polynomial/dynamic x repro3/final: no `gracefo` left; 05 `wavelengthFactor` = 1;
  04/05 read and write CHAMP files only in `champReducedDynamic/` and `output/<day>/reducedDynamic/`; TU Graz's
  daily loop kept. Comparison module run on synthetic orbit files (two orbits x two references, empty arc
  included): RMS values reproduce the simulated noise (3 cm, 1 cm).
- Element order of the new GROOPS programs checked against `readConfig` order in the GROOPS source
  (InstrumentSynchronize, PreprocessingVariationalEquationOrbitFit).

## Tests (2026-10-11, daily-loop version)

- Not run with GROOPS here (user decision 2026-10-11: the user's run is the test).
- Done here: Python compile check; script generation from the user's TU Graz scripts (01, 02, 03 kinematic,
  03 variational) for both options: all scripts keep TU Graz's daily loop (`sampling 1`); script 01 reads the bias
  file of each day (`TUG0R03FIN_{loopTime:%y%03O}..._OSB.BIA`); script 03 reads `signalBias_{loopTime:%D}`;
  polynomial: TU Graz's synchronization stays in 02; dynamic: it runs once, at the end of 02b, after the fit.

## Tests done (2026-10-10, before delivery; one-loop version)

- GROOPS release 2025-11-15 built from source on the build machine; RTKLIB 2.4.3 b34 (Ubuntu package).
- First run without by-hand files: folders created, run stops with the exact list (brdc per day, four repro3 zips).
- Script generation for repro3 / final / ultra, both a priori options: no `gracefo` left; 03 `wavelengthFactor` = 1;
  final/ultra: float ambiguities, transmitter biases removed, bias and attitude programs disabled.
- End-to-end with GROOPS on synthetic data (2 days, 10 s): truth orbit from GROOPS SimulateOrbit; rough positions =
  truth + 2.5 m noise with gaps of 20 s, 3 min and 10 min; attitude with a 60-s gap. Both options ran through
  steps 1-8: GROOPS 02 (Sp3Format2Orbit with SP3 `EP` records -> 3 m covariances), 02b (polynomial resampling;
  dynamic: 5 arcs, fit a-posteriori sigma 0.84 x 3 m = 2.5 m = the simulated noise), InstrumentSynchronize, report.
- Not testable here: TU Graz's real scripts (TU Graz server blocked from the build machine; stand-in scripts with the
  structure assumed by the old code were used), GROOPS GnssProcessing (kinematic PPP) with real CHAMP data, RTKLIB
  with real CHAMP RINEX (the RTKLIB code is unchanged from the old GPS-only code, which was tested on synthetic RINEX).

## Sources

- GROOPS: Mayer-Gürr et al. 2021, Comput. Geosci. 155, 104864; source release 2025-11-15.
- Earth-fixed file (NEW 2026-10-13): GROOPS source programs orbit2EarthFixedOrbit.cpp, instrumentRotate.cpp,
  instrumentEarthRotation.cpp, simulateAccelerometer.cpp, tidesAstronomical.cpp (release 2025-11-15); GOCO06s: Kvas et al.
  2021, Earth Syst. Sci. Data 13:99-118 (degree 120 as in the TU Graz force model).
- Kinematic PPP with GROOPS: Zehentner & Mayer-Gürr 2016, J. Geod. 90:275–286; Suesser-Rechberger et al. 2022,
  Adv. Space Res. 69(10):3559–3570. PPP: Zumberge et al. 1997, J. Geophys. Res. 102(B3):5005–5017.
- Dynamical smoothing of code single-point solutions as a priori orbit: Montenbruck et al. 2005,
  Aerosp. Sci. Technol. 9:261–271.
- SLR validation of LEO orbits: Arnold et al. 2019, J. Geod. 93:2315–2334; screening: Strugarek et al. 2022,
  GPS Solut. 26:104. CHAMP retroreflector: Neubert, Grunwaldt & Neubert, "The Retro-Reflector for the CHAMP
  Satellite: Final Design and Realization" (ILRS workshop). Troposphere: Mendes & Pavlis 2004 (GROOPS implementation).
- Reduced-dynamic orbit determination: Wu, Yunck & Thornton 1991, J. Guid. Control Dyn. 14(1):24–30;
  pseudo-stochastic pulses: Jäggi, Hugentobler & Beutler 2006, J. Geod. 80:47–60.
- GROOPS reduced-dynamic LEO POD (variational equations, leoDynamicOrbits): Mayer-Gürr et al. 2021 (above);
  TU Graz scenario `scenarioLeoReducedDynamicOrbit`.
- RTKLIB: Takasu & Yasuda 2009, Int. Symp. GPS/GNSS, Jeju.
- CHAMP RINEX types: Köhler (GFZ) 2001, "RINEX format observable extensions for CHAMP SST Data".
- SP3-c format (EP records): S. Hilla (NGS), "The Extended Standard Product 3 Orbit Format (SP3-c)", IGS format document.

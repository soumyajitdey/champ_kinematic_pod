"""Step 9: comparison of the kinematic and the reduced-dynamic orbit with TU Graz's published CHAMP orbits (confirmed item E).

References (validation only, never used in the processing):
  TU Graz CHAMP kinematic orbit         ftp.tugraz.at/pub/ITSG/satelliteOrbitProducts/operational/CHAMP/kinematicOrbit
  TU Graz CHAMP reduced-dynamic orbit   .../CHAMP/reducedDynamicOrbit
Differences (ours - reference) at common epochs, rotated into radial (R), along-track (T), cross-track (N) with the
reference position and velocity; a kinematic reference has no velocity, so the velocity for the frame axes is
taken by numerical differentiation of its positions (orients the axes only). Reused from the old code
(core/plot_errors.py, core/compare.py). CHANGED 2026-10-11: two orbits of this run (kinematic PPP and
reduced-dynamic POD), each compared with both TU Graz orbits.
Output: one PNG per (orbit, reference) pair, RMS per component, number of compared epochs.
"""
from pathlib import Path

import numpy as np

from core import download, settings
from core.groops_io import arc_starts, read_orbit, read_orbit_table   # CHANGED 2026-10-11: arc_starts

INK, MUTED, GRID, LINE = "#1f1f1e", "#6b6a64", "#e6e5e0", "#2a78d6"
ARC = "#d6542a"                                  # NEW 2026-10-11: colour of the arc-start lines
REFERENCES = [("kinematicOrbit", "TU Graz kinematic orbit"),
              ("reducedDynamicOrbit", "TU Graz reduced-dynamic orbit")]


def _match(t1, t2):
    """Indices of common epochs (rounded to 1 ms)."""
    k1 = np.round(t1 * 86400e3).astype(np.int64)
    k2 = np.round(t2 * 86400e3).astype(np.int64)
    _, i1, i2 = np.intersect1d(k1, k2, return_indices=True)
    return i1, i2


def _rtn(dpos, pos, vel):
    """Rotate position differences into radial / along-track (T) / cross-track (N)."""
    r = pos / np.linalg.norm(pos, axis=1)[:, None]
    n = np.cross(pos, vel)
    n /= np.linalg.norm(n, axis=1)[:, None]
    t = np.cross(n, r)
    return np.c_[(dpos * r).sum(1), (dpos * t).sum(1), (dpos * n).sum(1)]


def _frame_velocity(t, p, v):
    if v is not None and np.any(v):
        return v
    return np.gradient(p, t * 86400.0, axis=0)


def load_reference(kind, day):
    """(t [MJD], pos [m], vel or None, file) of a TU Graz CHAMP orbit for one day, or None (message printed)."""
    url = settings.TUG_ORBITS.format(kind=kind, year=day[:4], day=day)
    try:
        p = download.fetch_url([url], settings.DOWNLOADS / "champ" / "TUG" / Path(url).name)
        t, pos, vel = read_orbit_table(p)
        return t, pos, vel, str(p)
    except SystemExit as e:
        print(f"[validate] {e}")
        return None


def _rows(t, p, kind, lines, files):
    """Differences of one orbit (t, p) to one TU Graz reference, day by day. Returns (hours, errors [cm])."""
    hours, errs = [], []
    for k, day in enumerate(settings.DAYS):
        ref = load_reference(kind, day)
        if ref is None:
            lines.append(f"{day:10} reference not available")
            continue
        tr, pr, vr, f = ref
        files.append(f)
        vr = _frame_velocity(tr, pr, vr)
        sel = (t >= settings.TIME_START + k) & (t < settings.TIME_START + k + 1)
        i, j = _match(t[sel], tr)
        if not len(i):
            lines.append(f"{day:10} no common epochs")
            continue
        e = _rtn(p[sel][i] - pr[j], pr[j], vr[j]) * 100
        hours.append((t[sel][i] - settings.TIME_START) * 24)
        errs.append(e)
        lines.append(f"{day:10} {len(i):7d} " + " ".join(f"{x:7.2f}" for x in e.mean(0)) + " "
                     + " ".join(f"{x:7.2f}" for x in np.sqrt((e**2).mean(0)))
                     + f" {np.sqrt((e**2).sum(1).mean()):7.2f}")
    return hours, errs


def compare(orbit_sets, out_dir):
    """orbit_sets: {name: list of daily orbit files} (CHANGED 2026-10-11: kinematic and reduced-dynamic orbit;
    TU Graz daily loop: one file per day, joined here). Every orbit is compared with every TU Graz reference.
    Returns (report lines, list of reference files used, number of compared epochs per (orbit, reference))."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines, files, counts = [], [], {}
    for name, orbit_files in orbit_sets.items():
        parts = [read_orbit(f) for f in orbit_files]
        arcs = (np.concatenate([np.r_[x[0][:1], arc_starts(f)] for x, f in zip(parts, orbit_files)])  # NEW 2026-10-11:
                if name == "reduced-dynamic" else np.array([]))     # NEW: start of every reduced-dynamic arc [MJD]
        t = np.concatenate([x[0] for x in parts])
        arcs = arcs[arcs > t.min()] if len(arcs) else arcs  # CHANGED 2026-10-12: first epoch (e.g. trimmed start) is no arc start
        p = np.concatenate([x[1] for x in parts])
        w = name.replace(" ", "-").split("-")
        tag = w[0] + "".join(x.capitalize() for x in w[1:])            # "reduced-dynamic" -> "reducedDynamic"
        for kind, label in REFERENCES:
            lines += ["", f"=== {name} orbit minus {label} [cm] ===",
                      f"{'day':10} {'epochs':>7} {'R mean':>7} {'T mean':>7} {'N mean':>7} "
                      f"{'R RMS':>7} {'T RMS':>7} {'N RMS':>7} {'3D RMS':>7}"]
            hours, errs = _rows(t, p, kind, lines, files)
            counts[f"{name} orbit vs {label}"] = int(sum(len(h) for h in hours))
            if not hours:
                continue
            h, e = np.concatenate(hours), np.concatenate(errs)
            rms = np.sqrt((e**2).mean(0))
            lines.append(f"{'all days':10} {len(h):7d} " + " ".join(f"{x:7.2f}" for x in e.mean(0)) + " "
                         + " ".join(f"{x:7.2f}" for x in rms) + f" {np.sqrt((e**2).sum(1).mean()):7.2f}")
            lim = max(np.percentile(np.abs(e), 99.9) * 1.1, 0.1)
            fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
            for c, comp in enumerate(["Radial", "Along-track", "Cross-track"]):
                ax = axes[c]
                ax.plot(h, e[:, c], ".", ms=1.5, color=LINE)
                for b in range(1, len(settings.DAYS)):
                    ax.axvline(24 * b, color=MUTED, lw=0.6, ls=":")
                for a in arcs:                                                     # NEW 2026-10-11: dashed line
                    ax.axvline((a - settings.TIME_START) * 24, color=ARC, lw=0.6, ls="--")  # NEW: at each arc start
                ax.text(0.01, 0.95, f"RMS {rms[c]:.2f} cm", transform=ax.transAxes, va="top", fontsize=9,
                        color=INK, bbox=dict(fc="white", ec="none", alpha=0.8))
                ax.set_ylim(-lim, lim)
                ax.set_ylabel(f"{comp} [cm]", color=INK)
                ax.grid(color=GRID, lw=0.8)
                ax.tick_params(colors=MUTED, labelsize=8)
                for s in ax.spines.values():
                    s.set_color(GRID)
            n_out = int((np.abs(e) > lim).sum())
            axes[-1].set_xlabel(f"Hours since {settings.START} 00:00 (GPS time)", color=INK)
            fig.suptitle(f"CHAMP {settings.START} to {settings.END}: {name} orbit minus {label}, {len(h)} epochs"
                         + (f"\n{n_out} values beyond axis" if n_out else "")   # CHANGED 2026-10-11: own line (title was cut)
                         + ((("; " if n_out else "\n") + f"dashed lines: start of each of the {len(arcs)} "
                             "reduced-dynamic arcs") if len(arcs) else ""),                     # NEW 2026-10-11
                         color=INK, x=0.01, ha="left")
            fig.tight_layout()
            fig.savefig(out_dir / f"{tag}_minus_TUG_{kind}.png", dpi=150)
            plt.close(fig)
    return lines, sorted(set(files)), counts

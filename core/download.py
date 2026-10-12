"""Download and unpack everything the pipeline needs from TU Graz.

- GROOPS general data set (data.zip): Earth rotation, gravity field (GOCO06s), tides (FES2014b,
  DE432 ephemerides), thermosphere (JB2008, HWM14), CERES radiation, satellite macro models,
  GNSS transmitter metadata, LEO receiver metadata.
- TU Graz example scenarios: XML scripts, GRACE-FO L1B data, TUG repro3 GPS products,
  reference results.

CHANGED: nothing that already exists is downloaded or extracted again:
- a finished download is skipped; an interrupted one resumes from where it stopped
- an unpacked folder is reused; its zip is only opened if files are missing
- an interrupted unpack continues; files already extracted (same size) are skipped
- nothing is deleted
"""
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from core import settings as config                                 # CHANGED: shared settings

KEY = "gnss/transmitter/transmitterList.gps.txt"   # CHANGED: marks the GROOPS data root


def _fetch(rel_path, dest):
    """Download rel_path from the first TU Graz base URL that has it."""
    return fetch_url([f"{base}/{rel_path}" for base in config.TUG_BASES], dest)    # CHANGED


def fetch_url(urls, dest):                                                      # CHANGED: any server
    """Download the first URL that works into dest (skip if present, resume if partial)."""
    dest = Path(dest)
    if dest.exists():
        print(f"[download] have {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    errors = []
    for url in urls:                                                            # CHANGED
        try:
            have = tmp.stat().st_size if tmp.exists() else 0           # CHANGED: resume partial download
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
            print(f"[download] {url}" + (f" (resuming at {have/1e6:.1f} MB)" if have else ""))
            with urllib.request.urlopen(req, timeout=120) as r:
                if have and r.status != 206:                             # CHANGED: server ignored the range
                    have = 0
                total = have + int(r.headers.get("Content-Length") or 0)
                done = have
                with open(tmp, "ab" if have else "wb") as f:             # CHANGED: append when resuming
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            print(f"\r  {done/1e6:8.1f} / {total/1e6:.1f} MB", end="", flush=True)
                print()
            if total and done != total:
                raise IOError(f"incomplete: {done} of {total} bytes")
            tmp.rename(dest)
            return dest
        except urllib.error.HTTPError as e:
            if e.code == 416 and tmp.exists():                           # CHANGED: partial file is already complete
                tmp.rename(dest)
                return dest
            errors.append(f"{url}: {e}")
        except (urllib.error.URLError, IOError) as e:
            errors.append(f"{url}: {e}")                                 # CHANGED: keep partial file for resume
    sys.exit("[download] failed (partial file kept, rerun to resume):\n  " + "\n  ".join(errors))


def _extract(zf, members, dest):
    """CHANGED: extract members into dest, skipping files already there with the same size."""
    todo = [m for m in members if not m.endswith("/")
            and not ((Path(dest) / m).is_file() and (Path(dest) / m).stat().st_size == zf.getinfo(m).file_size)]
    if todo:
        size = sum(zf.getinfo(m).file_size for m in todo)
        print(f"[download] extracting {len(todo)} files ({size/1e9:.2f} GB), "
              f"{len(members) - len(todo)} already present")
    for m in todo:
        zf.extract(m, dest)


def _unzip(zip_path, target):
    target = Path(target)
    if target.exists():
        return target
    print(f"[download] unpacking {Path(zip_path).name}")
    tmp = target.with_name(target.name + ".part")
    with zipfile.ZipFile(zip_path) as z:
        _extract(z, z.namelist(), tmp)                                   # CHANGED: continue, no delete
    tmp.rename(target)
    return target


def _data_root(folder):
    """Folder that holds the GROOPS data (contains gnss/transmitter/transmitterList.gps.txt), or None."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    for p in [folder] + [q for q in sorted(folder.iterdir()) if q.is_dir()]:   # CHANGED: no deep scan of 25 GB
        if (p / KEY).is_file():
            return p
    return None


def _needed_paths(scenario_dirs, prns, extra=()):
    """Paths below groopsDataDir referenced by the scenario scripts, {prn} expanded."""
    from core import run_groops                                       # CHANGED
    paths = set(extra)                                                # CHANGED: mission-specific extra files (optional)
    for d in scenario_dirs:
        for s in sorted(Path(d).glob("0*.xml")):
            for p in run_groops.required_data_files(s):
                paths |= {p.replace("{prn}", x) for x in prns} if "{prn}" in p else {p}
    return paths


def get_groops_data(scenario_dirs, extra=()):                       # CHANGED: extra = optional mission files
    """Return path to the GROOPS data directory (the value of groopsDataDir).

    Only the files the scenario scripts reference ({groopsDataDir}/...) are extracted, not the
    whole data.zip. GROOPS reads no other data files here: OPTIONAL settings with default paths
    are not applied when absent (GROOPS config.cpp, getConfigText).
    """
    target = config.WORK / "groopsData"
    folder = target if target.exists() else target.with_name(target.name + ".part")

    # CHANGED: 1. use what is already on disk (full or partial unpack); no zip needed if complete
    root = _data_root(folder)
    if root is not None:
        paths = _needed_paths(scenario_dirs, (root / KEY).read_text().split(), extra)
        missing = sorted(p for p in paths if not (root / p).exists() and p not in extra)  # CHANGED: mission extras optional
        if not missing and folder == target:
            print(f"[download] have GROOPS data ({root})")
            return root
        if missing:
            print(f"[download] {len(missing)} needed data files not yet extracted")

    # 2. extract only the missing needed files from data.zip
    z = _fetch(config.DATA_ZIP, config.DOWNLOADS / config.DATA_ZIP)
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        prefix = next((n[:-len(KEY)] for n in names if n.endswith(KEY) and (n == KEY or n[-len(KEY)-1] == "/")), None)
        if prefix is None:
            sys.exit(f"[download] {KEY} not found in {z}")
        paths = _needed_paths(scenario_dirs, zf.read(prefix + KEY).decode().split(), extra)
        members, missing = [prefix + KEY], []
        for p in sorted(paths):
            hit = [n for n in names if n == prefix + p or n.startswith(prefix + p.rstrip("/") + "/")]
            (members.extend(hit) if hit else missing.append(p))
        opt = [p for p in missing if p in extra]                           # CHANGED: mission extras optional
        if opt:
            print("[download] WARNING not in data.zip (steps using them will stop with a message):\n  " + "\n  ".join(opt))
        missing = [p for p in missing if p not in extra]                   # CHANGED
        if missing:
            sys.exit("[download] not in data.zip:\n  " + "\n  ".join(missing))
        _extract(zf, members, folder)
    if folder != target:
        folder.rename(target)
    root = _data_root(target)
    if root is None:
        sys.exit(f"[download] no GROOPS data root found in {target}")
    return root


def get_scenario(name):
    """Return path to the pristine (never modified) scenario folder."""
    s = config.SCENARIOS[name]
    target = config.WORK / "scenarios" / name
    if not target.exists():                                              # CHANGED: zip only needed if not unpacked
        z = _fetch(s["zip"], config.DOWNLOADS / Path(s["zip"]).name)
        _unzip(z, target)
    if s["dir"] is None:                                                 # NEW 2026-10-11: folder name not known
        return target
    folder = target / s["dir"]
    if not folder.is_dir():
        sys.exit(f"[download] {s['dir']} not found in {target}")
    return folder



def scenario_zip_info(name):                                             # NEW 2026-10-10 (confirmed item C)
    """(zip path, download date, SHA-256) of a downloaded TU Graz scenario zip, for the report.
    The scenario zips carry no version number; the checksum identifies exactly which version was used."""
    import hashlib
    import time
    z = config.DOWNLOADS / Path(config.SCENARIOS[name]["zip"]).name
    if not z.is_file():
        return str(z), "zip file not found", "-"
    h = hashlib.sha256()
    with open(z, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return str(z), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(z.stat().st_mtime)), h.hexdigest()


def fetch_data_file(root, rel_path):                                    # NEW 2026-10-11 (SLR validation)
    """One file of the GROOPS data set, downloaded on its own from the TU Graz data folder (data/<rel_path>)
    into the local GROOPS data directory, if not already there. Avoids opening data.zip for a few small files."""
    dest = Path(root) / rel_path
    if dest.exists():
        return dest
    return fetch_url([f"{base}/data/{rel_path}" for base in config.TUG_BASES], dest)

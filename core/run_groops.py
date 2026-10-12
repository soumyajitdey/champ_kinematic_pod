"""Run GROOPS scripts in run folders (mission-independent engine).

Settings are passed only as GROOPS global variables (--global), which override the XML values
(GROOPS config.cpp): groopsDataDir, timeStart/timeEnd (mission dates), kinematicDir (option C).
Nothing is deleted or overwritten: every run gets a new folder.
"""
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_DATA_REF = re.compile(r"\{groopsDataDir\}/([^<>\s]+)")
OK = "RUN_OK"   # marker written after a run finished without error


def required_data_files(script):
    """Paths below groopsDataDir referenced by the enabled programs of one XML script."""
    def walk(node):
        if node.get("disabled") == "1":
            return
        if node.text:
            yield from _DATA_REF.findall(node.text)
        for child in node:
            yield from walk(child)
    return sorted(set(walk(ET.parse(script).getroot())))


def check_data(scripts, data_dir):
    """Stop with a list of every missing groopsDataDir file before GROOPS starts."""
    data_dir = Path(data_dir)
    prn_list = data_dir / "gnss/transmitter/transmitterList.gps.txt"
    prns = prn_list.read_text().split() if prn_list.is_file() else []
    missing = []
    for s in scripts:
        for rel in required_data_files(s):
            paths = [rel.replace("{prn}", p) for p in prns] if "{prn}" in rel else [rel]
            paths = [p if "{" not in p else p[:p.index("{")].rsplit("/", 1)[0] for p in paths]  # {station}/{svn} templates -> check folder
            missing += [f"{Path(s).name}: {p}" for p in paths if not (data_dir / p).exists()]
    if missing or not prns:
        sys.exit("[run] missing in GROOPS data directory " + str(data_dir) + ":\n  "
                 + "\n  ".join(missing or ["gnss/transmitter/transmitterList.gps.txt"]))


def copy(src, dst):
    """Copy file contents only (byte-identical). shutil.copy2/copytree also copy timestamps,
    which Windows drives under /mnt/* (WSL) can refuse with 'Operation not permitted'."""
    src, dst = Path(src), Path(dst)
    if src.is_dir():
        for f in sorted(src.rglob("*")):
            out = dst / f.relative_to(src)
            if f.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, out)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def prepare(run_dir, files):
    """New run folder. files: {name in run folder: Path (file/folder to copy) or str (file content)}."""
    run_dir = Path(run_dir)
    if run_dir.exists():
        sys.exit(f"[run] {run_dir} exists; refusing to overwrite")
    run_dir.mkdir(parents=True)
    for name, src in files.items():
        if isinstance(src, str):
            (run_dir / name).parent.mkdir(parents=True, exist_ok=True)
            (run_dir / name).write_text(src)
        else:
            copy(src, run_dir / name)
    return run_dir


def run_scripts(run_dir, scripts, data_dir, groops_exe, globals_=None):
    """Run XML scripts (names inside run_dir) in order; stop on the first GROOPS error."""
    run_dir = Path(run_dir)
    paths = [run_dir / s for s in scripts]
    check_data(paths, data_dir)
    log_dir = run_dir / "log"
    log_dir.mkdir(exist_ok=True)
    glob = {"groopsDataDir": str(Path(data_dir).resolve()), **(globals_ or {})}
    for s in paths:
        print(f"[run] {run_dir.name}: {s.name}")
        cmd = [groops_exe, "--log", str(log_dir / (s.stem + ".log"))]
        for k, v in glob.items():
            cmd += ["--global", f"{k}={v}"]
        if subprocess.run(cmd + [s.name], cwd=run_dir).returncode != 0:
            sys.exit(f"[run] GROOPS failed on {s.name}; see {log_dir / (s.stem + '.log')}")

"""
legacy_download.py - copied from leo-gps-pod (leo_gps_pod/champ_download.py, commit 3ba6bf3) and reused
for the GROOPS pipeline. CHANGED lines are marked; everything else is unchanged.
REMOVED 2026-10-10: fetch_champ_rso() and download_all() (no CHAMP RSO anywhere in this pipeline).

champ_download.py - automatic download of every input product, trying mirrors in order.

Products and sources (tried in the order listed; "confirmed" = path checked while writing this code)
  IGS final orbits igsWWWWD.sp3.Z and 30-s clocks igsWWWWD.clk_30s.Z
      SOPAC garner.ucsd.edu (confirmed), NASA CDDIS (confirmed, needs an Earthdata login in ~/.netrc),
      IGN France, BKG Germany, ESA GSSC, Wuhan University (IGS global data centres; paths unconfirmed)
  ANTEX igs05_1627.atx (frame of the 2010 IGS products)
      files.igs.org pcv_archive (confirmed), RTKLIB repository copy of igs05_1627 (confirmed)
  CHAMP GPS observations CH-OG-1-SST+YYYY_DDD_00_R.9.zip        GFZ ISDC (confirmed), GFZ ISDC FTP
  CHAMP attitude CH-ME-3-ASC-BOOM+YYYY_DDD_00.9.zip               GFZ ISDC (confirmed), GFZ ISDC FTP
Every file is checked (compression header, content, date of first epoch). A report of what was
downloaded, skipped or failed (with the reason) is printed and written to download_report.txt.
"""
import gzip
import netrc
import os
import re
import time
import urllib.request
import zipfile
from datetime import date, timedelta

import requests

GFZ = "https://isdc-data.gfz.de/champ"
GFZ_FTP = "ftp://isdcftp.gfz-potsdam.de/champ"
IGS_MIRRORS = [
    "http://garner.ucsd.edu/pub/products/{wk}/{name}",
    "https://cddis.nasa.gov/archive/gnss/products/{wk}/{name}",
    "https://igs.ign.fr/pub/igs/products/{wk}/{name}",
    "ftp://igs.ign.fr/pub/igs/products/{wk}/{name}",
    "https://igs.bkg.bund.de/root_ftp/IGS/products/{wk}/{name}",
    "https://igs.bkg.bund.de/root_ftp/IGS/products/orbits/{wk}/{name}",
    "https://gssc.esa.int/igs/products/{wk}/{name}",
    "ftp://igs.gnsswhu.cn/pub/gps/products/{wk}/{name}",
]
ATX_NAME = "igs05_1627.atx"
ATX_MIRRORS = [
    "https://files.igs.org/pub/station/general/pcv_archive/igs05_1627.atx",
    "https://raw.githubusercontent.com/tomojitakasu/RTKLIB/master/data/igs05.atx",
    "ftp://igs.ign.fr/pub/igs/station/general/pcv_archive/igs05_1627.atx",
]
UA = {"User-Agent": "champ_ppp-downloader/1.0"}


class Report:
    def __init__(self):
        self.rows = []

    def add(self, product, day, status, detail):
        self.rows.append((product, str(day), status, detail))
        print("  %-5s %-10s %-11s %s" % (status, product, str(day), detail))

    def failed(self):
        return [r for r in self.rows if r[2] == "FAIL"]

    def write(self, path):
        with open(path, "w") as f:
            f.write("%-10s %-11s %-6s %s\n" % ("product", "day", "status", "detail"))
            for r in self.rows:
                f.write("%-10s %-11s %-6s %s\n" % (r[0], r[1], r[2], r[3]))


def gps_week_dow(d):
    n = (d - date(1980, 1, 6)).days
    return n // 7, n % 7


def _earthdata_session():
    try:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        auth = None
    if not auth:
        return None

    class S(requests.Session):
        def rebuild_auth(self, prepared_request, response):   # keep auth only for the Earthdata host
            h = prepared_request.headers
            if "Authorization" in h:
                o = requests.utils.urlparse(response.request.url).hostname
                r = requests.utils.urlparse(prepared_request.url).hostname
                if o != r and "urs.earthdata.nasa.gov" not in (o, r):
                    del h["Authorization"]
    s = S()
    s.auth = (auth[0], auth[2])
    return s


def _curl_cddis(url, timeout):                                     # CHANGED: new
    """CDDIS download as documented by CDDIS: curl -n (~/.netrc) -L with a cookie file.
    Returns bytes, raises on HTTP 404, None if curl is missing or fails otherwise."""
    import shutil, subprocess
    if not shutil.which("curl"):
        return None
    jar = os.path.expanduser("~/.cddis_cookies")
    r = subprocess.run(["curl", "-n", "-L", "-s", "-c", jar, "-b", jar, "--max-time", str(timeout * 5),
                        "-w", "\n%{http_code}", url], capture_output=True)
    body, _, code = r.stdout.rpartition(b"\n")
    if code.strip() == b"200":
        return body
    if code.strip() == b"404":
        raise RuntimeError("HTTP 404")
    print(f"[download] curl {url}: HTTP {code.decode(errors='replace').strip()}")
    return None


_SESSION = requests.Session()
_EARTHDATA = None


def get(url, timeout=60, retries=2):
    """Return the bytes at url (http/https/ftp) or raise with a short reason."""
    global _EARTHDATA
    last = None
    for attempt in range(retries):
        try:
            if url.startswith("ftp://"):
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return r.read()
            sess = _SESSION
            if "cddis.nasa.gov" in url:
                if _EARTHDATA is None:
                    _EARTHDATA = _earthdata_session() or False
                if not _EARTHDATA:
                    raise RuntimeError("CDDIS needs an Earthdata login in ~/.netrc (skipped)")
                sess = _EARTHDATA
                b = _curl_cddis(url, timeout)                       # CHANGED: CDDIS-documented curl method first
                if b is not None:                                   # CHANGED
                    return b                                        # CHANGED
            r = sess.get(url, timeout=timeout, headers=UA)
            if r.status_code != 200:
                raise RuntimeError("HTTP %d" % r.status_code)
            return r.content
        except RuntimeError as e:
            last = str(e)
            if "HTTP 404" in last or "skipped" in last:
                break
        except Exception as e:                                # network errors: retry
            last = "%s: %s" % (e.__class__.__name__, str(e)[:80])
        time.sleep(1.0 + attempt)
    raise RuntimeError(last or "unknown error")


def listing(url):
    """File names in an HTTP or FTP directory listing."""
    b = get(url).decode("latin-1", "replace")
    if url.startswith("ftp://"):
        return [l.split()[-1] for l in b.splitlines() if l.strip()]
    return sorted(set(re.findall(r'href="([^"?/][^"]*)"', b)))


def _unZ(b):
    import subprocess                                                   # CHANGED: gzip -dc reads .Z (no unlzw3 package needed)
    return subprocess.run(["gzip", "-dc"], input=b, capture_output=True, check=True).stdout   # CHANGED


def _first_sp3_date(text):
    for line in text.splitlines():
        if line.startswith("* "):
            f = line[1:].split()
            return date(int(f[0]), int(f[1]), int(f[2]))
    return None


def _first_clk_date(text):
    hdr = True
    for line in text.splitlines():
        if hdr:
            hdr = "END OF HEADER" not in line
            continue
        if line.startswith("AS "):
            f = line.split()
            return date(int(f[2]), int(f[3]), int(f[4]))
    return None


def fetch_igs(day, out_dir, report):
    """IGS final orbit + 30-s clock for one day (plain text files in out_dir)."""
    wk, dow = gps_week_dow(day)
    paths = {}
    for ext, first in (("sp3", _first_sp3_date), ("clk_30s", _first_clk_date)):
        name = "igs%d%d.%s" % (wk, dow, ext)
        out = os.path.join(out_dir, name)
        if os.path.exists(out) and first(open(out, errors="replace").read(200000)) == day:
            report.add("IGS " + ext, day, "have", out)
            paths[ext] = out
            continue
        errors = []
        for tmpl in IGS_MIRRORS:
            url = tmpl.format(wk=wk, name=name + ".Z")
            try:
                b = get(url)
                if b[:2] != b"\x1f\x9d":
                    raise RuntimeError("not a .Z file (login page?)")
                text = _unZ(b).decode("ascii", "replace")
                d0 = first(text)
                if d0 != day:
                    raise RuntimeError("first epoch %s, expected %s" % (d0, day))
                with open(out, "w") as f:
                    f.write(text)
                report.add("IGS " + ext, day, "OK", "%s from %s" % (name, url.split("/")[2]))
                paths[ext] = out
                break
            except Exception as e:
                errors.append("%s: %s" % (url.split("/")[2], e))
        else:
            report.add("IGS " + ext, day, "FAIL", "%s - %s" % (name, "; ".join(errors)))
    return paths


def fetch_igu(day, out_dir, report):                                     # CHANGED: new, ultra-rapid product
    """IGS ultra-rapid orbit+clock SP3 covering `day` with observed data: file of day+1, 00 UTC issue
    (its first 24 h are the observed half). Plain text file in out_dir. Same mirrors as fetch_igs."""
    nxt = day + timedelta(days=1)
    wk, dow = gps_week_dow(nxt)
    name = "igu%d%d_00.sp3" % (wk, dow)
    out = os.path.join(out_dir, name)
    if os.path.exists(out) and _first_sp3_date(open(out, errors="replace").read(200000)) == day:
        report.add("IGU sp3", day, "have", out)
        return out
    errors = []
    for tmpl in IGS_MIRRORS:
        url = tmpl.format(wk=wk, name=name + ".Z")
        try:
            b = get(url)
            if b[:2] != b"\x1f\x9d":
                raise RuntimeError("not a .Z file (login page?)")
            text = _unZ(b).decode("ascii", "replace")
            d0 = _first_sp3_date(text)
            if d0 != day:
                raise RuntimeError("first epoch %s, expected %s" % (d0, day))
            with open(out, "w") as f:
                f.write(text)
            report.add("IGU sp3", day, "OK", "%s from %s" % (name, url.split("/")[2]))
            return out
        except Exception as e:
            errors.append("%s: %s" % (url.split("/")[2], e))
    report.add("IGU sp3", day, "FAIL", "%s - %s" % (name, "; ".join(errors)))
    return None


def fetch_antex(out_dir, report):
    out = os.path.join(out_dir, ATX_NAME)
    if os.path.exists(out) and "IGS05_1627" in open(out, errors="replace").read(400000):
        report.add("ANTEX", "-", "have", out)
        return out
    errors = []
    for url in ATX_MIRRORS:
        try:
            b = get(url)
            text = b.decode("ascii", "replace")
            if "ANTEX VERSION" not in text[:400] or "IGS05_1627" not in text:
                raise RuntimeError("not igs05_1627")
            with open(out, "w") as f:
                f.write(text)
            report.add("ANTEX", "-", "OK", "from %s" % url.split("/")[2])
            return out
        except Exception as e:
            errors.append("%s: %s" % (url.split("/")[2], e))
    report.add("ANTEX", "-", "FAIL", "; ".join(errors))
    return None


def _zip_ok(path, test):
    try:
        with zipfile.ZipFile(path) as z:
            for m in z.infolist():
                if test(z.read(m).decode("ascii", "replace")):
                    return True
    except Exception:                                  # corrupt / truncated / unsupported archive
        return False
    return False


def _is_rnx(text):
    return "RINEX VERSION" in text[:200] and "OBSERVATION" in text[:200]


def _is_asc(text):
    return "\ntim " in text[:5000] or text.startswith("tim ")


def _fetch_gfz(product, subdir, prefix, day, out_dir, report, test):
    """One GFZ ISDC zip file: direct name, then directory listing; HTTPS then FTP."""
    y, doy = day.year, day.timetuple().tm_yday
    stem = "%s+%d_%03d_" % (prefix, y, doy)
    for f in os.listdir(out_dir):
        p = os.path.join(out_dir, f)
        if f.startswith(stem) and f.endswith(".zip") and _zip_ok(p, test):
            report.add(product, day, "have", p)
            return p
    errors = []
    for root in (GFZ, GFZ_FTP):
        base = "%s/%s/%d/" % (root, subdir, y)
        guess = [stem + ("00_R.9.zip" if "SST" in prefix else "00.9.zip")]
        try:
            names = [n for n in listing(base) if n.startswith(stem) and n.endswith(".zip")]
            guess = sorted(set(guess) | set(names))
        except Exception as e:
            errors.append("listing %s: %s" % (root.split("/")[2], e))
        for name in guess:
            url = base + name
            try:
                b = get(url, timeout=120)
                if b[:2] != b"PK":
                    raise RuntimeError("not a zip file")
                out = os.path.join(out_dir, name)
                with open(out, "wb") as f:
                    f.write(b)
                if not _zip_ok(out, test):
                    os.remove(out)
                    raise RuntimeError("zip content not as expected")
                report.add(product, day, "OK", "%s from %s" % (name, url.split("/")[2]))
                return out
            except Exception as e:
                errors.append("%s %s: %s" % (url.split("/")[2], name, e))
    report.add(product, day, "FAIL", "; ".join(errors))
    return None


def fetch_champ_rinex(day, out_dir, report):
    return _fetch_gfz("RINEX", "OG/Level1/SST", "CH-OG-1-SST", day, out_dir, report, _is_rnx)


def fetch_champ_attitude(day, out_dir, report):
    return _fetch_gfz("attitude", "ME/Level3/ASC-BOOM", "CH-ME-3-ASC-BOOM", day, out_dir, report, _is_asc)


def fetch_champ_acc(day, out_dir, report):                               # CHANGED: new, ACC+attitude for GROOPS Champ2AccStar
    return _fetch_gfz("ACC", "OG/Level2/ACC", "CH-OG-2-ACC", day, out_dir, report, _is_asc)

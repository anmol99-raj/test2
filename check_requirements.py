
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PYPI_PACKAGE_URL = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION_URL = "https://pypi.org/pypi/{name}/{version}/json"


LINE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"   
    r"(?:\[[^\]]*\])?"                             
    r"\s*(?:===?\s*(?P<version>[^\s;,#]*))?"      
)


def fetch_json(url):
    """Return (status_code, parsed_json_or_None)."""
    req = urllib.request.Request(url, headers={"User-Agent": "requirements-checker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def parse_line(line):
    """Return (name, version_or_None) or None if the line isn't a dependency."""
    line = line.split(" #")[0].strip()          
    if not line or line.startswith(("#", "-", "git+", "http://", "https://", ".")):
        return None                              
    m = LINE_RE.match(line)
    if not m:
        return None
    return m.group("name"), m.group("version")


def check_dependency(item):
    line_no, name, version = item
    result = {"line": line_no, "name": name, "version": version, "empty_pin": version == "",
              "pkg_exists": False, "ver_exists": None, "upload_time": None, "error": None}

    status, _ = fetch_json(PYPI_PACKAGE_URL.format(name=name))
    if status == 404:
        return result
    if status != 200:
        result["error"] = f"HTTP status {status} while checking package"
        return result
    result["pkg_exists"] = True

    if version is None or version == "":
        return result                           

    status, data = fetch_json(PYPI_VERSION_URL.format(name=name, version=version))
    if status == 404:
        result["ver_exists"] = False
        return result
    if status != 200 or data is None:
        result["error"] = f"HTTP status {status} while checking version"
        return result

    result["ver_exists"] = True
    urls = data.get("urls") or []
    if urls:
        result["upload_time"] = urls[0].get("upload_time_iso_8601") or urls[0].get("upload_time")
    return result


def parse_time(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python check_requirements.py <requirements-file>")

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    items = []
    for i, line in enumerate(lines, start=1):
        parsed = parse_line(line)
        if parsed:
            items.append((i, *parsed))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check_dependency, items))

    missing_pkgs = [r for r in results if not r["pkg_exists"] and not r["error"]]
    missing_vers = [r for r in results if r["pkg_exists"] and r["ver_exists"] is False]
    empty_pins = [r for r in results if r["empty_pin"]]
    errors = [r for r in results if r["error"]]
    dated = [r for r in results if r["upload_time"]]

    if dated:
        oldest = min(dated, key=lambda r: parse_time(r["upload_time"]))
        oldest_str = (f"{oldest['name']}=={oldest['version']} "
                      f"(uploaded {oldest['upload_time']}, line {oldest['line']})")
    else:
        oldest_str = "none"

    print(f"Dependencies checked : {len(lines)}")
    print(f"Packages not on PyPI : {len(missing_pkgs)}")
    print(f"Versions not on PyPI : {len(missing_vers)}")
    print(f"Oldest pinned version release : {oldest_str}")

    for r in errors: 
        print(f"warning: line {r['line']} ({r['name']}): {r['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
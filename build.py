#!/usr/bin/env python3
"""Build and validate BinTextly.

One source of truth: SITE_ORIGIN in site.config.js.
Pages are discovered from the filesystem, not listed twice: index.html at the
repository root is "/", and every directory holding an index.html is
"/<dir>/". Adding a page therefore means adding a directory — nothing to
register, nothing to forget.

  python3 build.py           # write canonical / robots.txt / sitemap.xml
  python3 build.py --check   # read-only validation, exit 1 on any problem

Domain switch: edit SITE_ORIGIN, run build.py, then build.py --check.
"""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "site.config.js"

# Absolute URLs may only point at SITE_ORIGIN or at these vocabularies.
ALLOWED_HOSTS = {"www.w3.org", "www.sitemaps.org", "schema.org"}

# File types that a browser or crawler actually consumes from the site.
SERVED_SUFFIXES = {".html", ".htm", ".css", ".js"}

# Directories that are not site sections.
SKIP_DIRS = {"tools", "node_modules"}

CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]*)"[^>]*>', re.I)
URL_RE = re.compile(r'https?://[^\s"\'<>)\]}]+')
HREF_RE = re.compile(r'href="([^"]+)"', re.I)
ABSOLUTE_RE = re.compile(r'^https?://', re.I)
ORIGIN_RE = re.compile(
    r'^\s*(?:export\s+)?(?:const|let|var)\s+SITE_ORIGIN\s*=\s*["\']([^"\']+)["\']',
    re.M,
)


def load_origin():
    if not CONFIG.exists():
        raise SystemExit("missing site.config.js")
    text = CONFIG.read_text(encoding="utf-8")
    match = ORIGIN_RE.search(text)
    if not match:
        raise SystemExit('site.config.js must declare SITE_ORIGIN = "https://..."')
    origin = match.group(1).rstrip("/")
    if not origin.startswith("https://"):
        raise SystemExit("SITE_ORIGIN must be an absolute https:// URL")
    return origin


def discover_pages():
    """[("/", path), ("/section/", path), ...] — root first, then alphabetical."""
    pages = []
    root_index = ROOT / "index.html"
    if root_index.exists():
        pages.append(("/", root_index))
    for path in sorted(ROOT.rglob("index.html")):
        rel = path.parent.relative_to(ROOT)
        if rel == Path("."):
            continue
        if any(part.startswith((".", "_")) or part in SKIP_DIRS for part in rel.parts):
            continue
        pages.append(("/" + rel.as_posix() + "/", path))
    return pages


def absolute(origin, page_path):
    return origin + page_path


# ---------- lastmod ----------

def _git(*args):
    try:
        result = subprocess.run(
            ("git",) + args, cwd=ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def lastmod(path):
    """Commit date for a clean file, today's date for a file with edits pending."""
    rel = path.relative_to(ROOT).as_posix()
    committed = _git("log", "-1", "--format=%cs", "--", rel)
    dirty = _git("status", "--porcelain", "--", rel)
    if committed and not dirty:
        return committed
    return date.today().isoformat()


# ---------- render ----------

def render_sitemap(origin, pages):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for page_path, path in pages:
        lines.append("  <url>")
        lines.append(f"    <loc>{absolute(origin, page_path)}</loc>")
        lines.append(f"    <lastmod>{lastmod(path)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def render_robots(origin):
    return f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n"


# ---------- normalise ----------

def normalise(origin, pages):
    """Pin every canonical to SITE_ORIGIN + page path."""
    changed = []
    for page_path, path in pages:
        text = path.read_text(encoding="utf-8")
        before = text
        expected = absolute(origin, page_path)
        if CANONICAL_RE.search(text):
            text = CANONICAL_RE.sub(f'<link rel="canonical" href="{expected}">', text)
        else:
            text = text.replace("</head>", f'<link rel="canonical" href="{expected}">\n</head>', 1)
        if text != before:
            path.write_text(text, encoding="utf-8")
            changed.append(path.relative_to(ROOT).as_posix())
    return changed


# ---------- validation ----------

def check_links(path, origin):
    """Every internal href must resolve on disk; absolute hrefs must stay on SITE_ORIGIN."""
    problems = []
    label = path.relative_to(ROOT).as_posix()
    for href in HREF_RE.findall(path.read_text(encoding="utf-8")):
        if href.startswith(("#", "mailto:", "data:", "tel:", "javascript:")):
            continue
        target = href
        if ABSOLUTE_RE.match(target):
            if target.rstrip("/") == origin:
                target = "/"
            elif target.startswith(origin + "/"):
                target = target[len(origin):]
            else:
                problems.append(f"{label}: absolute link leaves SITE_ORIGIN -> {href}")
                continue
        target = target.split("#")[0].split("?")[0]
        if not target:
            continue
        base = ROOT if target.startswith("/") else path.parent
        candidate = (base / target.lstrip("/")).resolve()
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists():
            problems.append(f"{label}: dead internal link -> {href}")
    return problems


def scan_hosts(origin):
    """Every absolute URL in served output must sit on SITE_ORIGIN or a known vocabulary."""
    allowed = {urlparse(origin).netloc} | ALLOWED_HOSTS
    problems = []
    targets = [ROOT / "robots.txt", ROOT / "sitemap.xml"]
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if not path.is_file() or path.suffix.lower() not in SERVED_SUFFIXES:
            continue
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            continue
        targets.append(path)
    for path in targets:
        if not path.exists():
            continue
        label = path.relative_to(ROOT).as_posix()
        for url in URL_RE.findall(path.read_text(encoding="utf-8")):
            if urlparse(url).netloc not in allowed:
                problems.append(f"{label}: absolute URL leaves the site -> {url}")
    return problems


def validate(origin, pages):
    problems = scan_hosts(origin)
    live_urls = set()

    for page_path, path in pages:
        label = path.relative_to(ROOT).as_posix()
        live_urls.add(absolute(origin, page_path))
        text = path.read_text(encoding="utf-8")

        canonicals = CANONICAL_RE.findall(text)
        expected = absolute(origin, page_path)
        if len(canonicals) != 1:
            problems.append(f"{label}: expected exactly 1 canonical, found {len(canonicals)}")
        elif canonicals[0] != expected:
            problems.append(f"{label}: canonical is {canonicals[0]}, expected {expected}")

        if not re.search(r"<title>\s*\S", text, re.I):
            problems.append(f"{label}: missing <title>")
        if not re.search(r'<meta\s+name="description"\s+content="\s*\S', text, re.I):
            problems.append(f"{label}: missing meta description")
        if len(re.findall(r"<h1[\s>]", text, re.I)) != 1:
            problems.append(f"{label}: expected exactly one <h1>")

        if re.search(r'<meta\s+name="robots"[^>]*noindex', text, re.I):
            problems.append(f"{label}: has a noindex robots meta")
        if re.search(r'<meta\s+name="keywords"', text, re.I):
            problems.append(f"{label}: has a meta keywords tag")

        problems.extend(check_links(path, origin))

    error_page = ROOT / "404.html"
    if not error_page.exists():
        problems.append("missing 404.html")
    else:
        if CANONICAL_RE.search(error_page.read_text(encoding="utf-8")):
            problems.append("404.html: must not declare a canonical")
        problems.extend(check_links(error_page, origin))

    sitemap_path = ROOT / "sitemap.xml"
    if not sitemap_path.exists():
        problems.append("missing sitemap.xml")
    else:
        sitemap = sitemap_path.read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        if set(locs) != live_urls:
            problems.append(f"sitemap.xml locs {sorted(locs)} != live pages {sorted(live_urls)}")
        if len(locs) != len(set(locs)):
            problems.append("sitemap.xml has duplicate <loc> entries")
        for value in re.findall(r"<lastmod>([^<]+)</lastmod>", sitemap):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                problems.append(f"sitemap.xml lastmod is not YYYY-MM-DD: {value}")
        if sitemap.count("<url>") != len(pages):
            problems.append("sitemap.xml needs exactly one <url> per live page")

    robots_path = ROOT / "robots.txt"
    if not robots_path.exists():
        problems.append("missing robots.txt")
    elif robots_path.read_text(encoding="utf-8") != render_robots(origin):
        problems.append("robots.txt does not match the generated content for SITE_ORIGIN")

    return problems


def main():
    origin = load_origin()
    pages = discover_pages()
    check_only = "--check" in sys.argv

    if not check_only:
        changed = normalise(origin, pages)
        (ROOT / "robots.txt").write_text(render_robots(origin), encoding="utf-8")
        (ROOT / "sitemap.xml").write_text(render_sitemap(origin, pages), encoding="utf-8")
        if changed:
            print("normalised canonical in: " + ", ".join(changed))

    problems = validate(origin, pages)
    if problems:
        print("FAIL")
        for problem in problems:
            print("  - " + problem)
        return 1

    print(f"OK  origin={origin}  pages={len(pages)}")
    for page_path, path in pages:
        print(f"    {absolute(origin, page_path)}  lastmod={lastmod(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

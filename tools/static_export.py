#!/usr/bin/env python3
"""
Controlled static exporter for a Grav site -> Cloudflare Pages.

Why not wget --mirror: Grav's taxonomy/pagination produce combinatorial
colon-param URL variants that a naive crawler explodes on. This fetches an
explicit seed set (sitemap pages + enumerated tags + sections), discovers ONLY
pagination links from listing pages (bounded), rewrites Grav's colon URLs
(/tag:ai -> /tag/ai/, /posts/page:2 -> /posts/page/2/) to Pages-friendly clean
paths, captures referenced assets, and writes _redirects / _headers.

Site-specific values (prod URL, sections, taxonomy/pagination route shapes,
posts dir) come from static-export.config.json — see tools/export_config.py.

Usage: python3 tools/static_export.py http://127.0.0.1:8092 ./output [config.json]
Run against a LOCAL Grav (Docker) so absolute URLs render with the prod Host.
"""
import sys, os, re, html, unicodedata, urllib.request, urllib.parse, posixpath
from collections import deque
from export_config import load_config

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8092'
OUT  = sys.argv[2] if len(sys.argv) > 2 else 'output'
CFG  = load_config(sys.argv[3] if len(sys.argv) > 3 else None)

PROD = CFG['site']['prod_url'].rstrip('/')
HOST = CFG['site']['host']
HEADERS = {'Host': HOST, 'X-Forwarded-Proto': 'https', 'User-Agent': 'static-export/1.0'}

EX = CFG['export']
POSTS_DIR   = EX['posts_dir']
SECTIONS    = EX['sections']                       # "/section": "Tag Display Name"
TAX_PARAM   = EX['taxonomy_param']
TAX_BASE    = EX['taxonomy_base'].rstrip('/') + '/'
PAGE_BASE   = EX['pagination_base'].rstrip('/') + '/'
PAGE_PREFIX = PAGE_BASE.rstrip('/')                # e.g. "/posts"
ARCH_PARAM  = EX['archives_param']
ARCH_BASE   = EX['archives_base'].rstrip('/') + '/'
ASSET_RE    = re.compile(r'^/(%s)/' % '|'.join(re.escape(p) for p in EX['asset_prefixes']))
DOWNLOAD_EXTS = {e.lower().lstrip('.') for e in EX['download_extensions']}


def fetch(path):
    url = BASE + path
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.headers.get_content_type(), r.read()


def slugify(s):
    s = html.unescape(urllib.parse.unquote(s)).strip().lower()
    s = s.replace('&', ' and ')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s


def clean_route(route):
    """Map a Grav route (may contain colon params) to a clean output route."""
    route = route.split('#')[0]
    m = re.match(r'^/%s:(.+?)(?:/page:(\d+))?$' % re.escape(TAX_PARAM), route)
    if m:
        base = '%s%s/' % (TAX_BASE, slugify(m.group(1)))
        return base + ('page/%s/' % m.group(2) if m.group(2) else '')
    m = re.match(r'^(?:%s)?/page:(\d+)$' % re.escape(PAGE_PREFIX), route)
    if m:
        return '%spage/%s/' % (PAGE_BASE, m.group(1))
    m = re.match(r'^/%s:(\d+)(?:/page:(\d+))?$' % re.escape(ARCH_PARAM), route)
    if m:
        base = '%s%s/' % (ARCH_BASE, m.group(1))
        return base + ('page/%s/' % m.group(2) if m.group(2) else '')
    if route in ('', '/'):
        return '/'
    return route.rstrip('/') + '/'


def out_path(clean):
    """Clean route -> file path under OUT (index.html for dir routes)."""
    if clean.endswith('/'):
        return os.path.join(OUT, clean.strip('/'), 'index.html')
    return os.path.join(OUT, clean.strip('/'))


LINK_RE = re.compile(r'''(href|src)=(["'])([^"']*)\2''')
PAGE_LINK_RE = re.compile(r'(?:%s)?/page:(\d+)' % re.escape(PAGE_PREFIX))


def rewrite_html(body):
    text = body.decode('utf-8', 'replace')
    # tag / pagination / archive links -> clean URLs, PRESERVING the #posts anchor
    # (the anchor scrolls past the hero to the post list, as on the live site).
    # allow spaces/&/encoded chars in the tag token (stop only at quote, #, < or >)
    text = re.sub(r"/%s:([^\"'#<>]+)(#posts)?" % re.escape(TAX_PARAM),
                  lambda m: '%s%s/%s' % (TAX_BASE, slugify(m.group(1)), m.group(2) or ''), text)
    text = re.sub(r'(?:%s)?/page:(\d+)(#posts)?' % re.escape(PAGE_PREFIX),
                  lambda m: '%spage/%s/%s' % (PAGE_BASE, m.group(1), m.group(2) or ''), text)
    text = re.sub(r'/%s:(\d+)(#posts)?' % re.escape(ARCH_PARAM),
                  lambda m: '%s%s/%s' % (ARCH_BASE, m.group(1), m.group(2) or ''), text)
    # section nav links -> clean tag URLs WITH #posts (matches the live 302 target)
    for sec, tag in SECTIONS.items():
        repl = '"%s%s/#posts"' % (TAX_BASE, slugify(tag))
        text = text.replace('"%s"' % sec, repl).replace('"%s/"' % sec, repl)
    # normalise any leftover http://<host> -> https prod origin
    text = text.replace('http://' + HOST, PROD)
    return text.encode('utf-8')


def collect_assets(text):
    assets = set()
    for _, _, url in LINK_RE.findall(text):
        # store the DECODED path (literal filename); the fetch step re-encodes it.
        u = urllib.parse.unquote(html.unescape(url)).split('#')[0].split('?')[0]
        if u.startswith(PROD):
            u = u[len(PROD):]
        if not u.startswith('/'):
            continue
        if ASSET_RE.match(u):
            assets.add(u)
        else:
            # downloadable page media (e.g. /posts/<slug>/file.pdf) — capture by extension
            last = u.rsplit('/', 1)[-1]
            ext = last.rsplit('.', 1)[-1].lower() if '.' in last else ''
            if ext in DOWNLOAD_EXTS:
                assets.add(u)
    return assets


def get_tags():
    """Parse distinct taxonomy terms from every post .md frontmatter."""
    tags = set()
    key_re = re.compile(r'^\s*%s:\s*\n((?:\s+-\s+.*\n)+)' % re.escape(TAX_PARAM), re.M)
    for root, _, files in os.walk(POSTS_DIR):
        for fn in files:
            if not fn.endswith('.md'):
                continue
            try:
                txt = open(os.path.join(root, fn), encoding='utf-8').read()
            except Exception:
                continue
            m = key_re.search(txt)
            if not m:
                continue
            for line in m.group(1).splitlines():
                v = line.strip().lstrip('-').strip().strip("'\"")
                if v:
                    tags.add(v)
    return tags


def get_years():
    """Distinct publish years (Grav date is DD-MM-YYYY) for archive pages."""
    years = set()
    for root, _, files in os.walk(POSTS_DIR):
        for fn in files:
            if not fn.endswith('.md'):
                continue
            try:
                txt = open(os.path.join(root, fn), encoding='utf-8').read()
            except Exception:
                continue
            m = re.search(r"^\s*date:\s*'?\d{2}-\d{2}-(\d{4})", txt, re.M)
            if m:
                years.add(m.group(1))
    return years


def main():
    os.makedirs(OUT, exist_ok=True)
    # --- seeds ---
    seeds = ['/']
    # posts from sitemap
    _, _, sm = fetch('/sitemap.xml')
    for loc in re.findall(r'<loc>([^<]+)</loc>', sm.decode()):
        p = loc.replace(PROD, '').strip()
        if p and p != '/':
            seeds.append(p if p.startswith('/') else '/' + p)
    # tags: enumerate from post frontmatter (self-contained, no fragile shell list)
    if EX['enumerate_tags']:
        for t in sorted(get_tags()):
            seeds.append('/%s:%s' % (TAX_PARAM, urllib.parse.quote(t)))
    # archive-by-year pages (linked from the archives widget)
    if EX['enumerate_archive_years']:
        for y in sorted(get_years()):
            seeds.append('/%s:%s' % (ARCH_PARAM, y))
    # sections render as their tag pages (already covered by tags); plus extras
    seeds.extend(EX['extra_seeds'])

    seen_routes, pages = set(), {}     # route -> (clean, body)
    assets = set()
    q = deque(seeds)
    while q:
        route = q.popleft()
        key = route.split('#')[0]
        if key in seen_routes:
            continue
        seen_routes.add(key)
        try:
            status, ctype, body = fetch(key)
        except Exception as e:
            print('  SKIP', key, e); continue
        if status != 200 or 'html' not in ctype:
            continue
        text = rewrite_html(body)
        clean = clean_route(key)
        pages[clean] = text
        assets |= collect_assets(text.decode('utf-8', 'replace'))
        # bounded pagination discovery: only enqueue page: links found on THIS listing
        for n in set(PAGE_LINK_RE.findall(body.decode('utf-8', 'replace'))):
            base = key.split('/page:')[0]
            if base.startswith('/%s:' % TAX_PARAM) or base.startswith('/%s:' % ARCH_PARAM):
                q.append('%s/page:%s' % (base, n))
            else:
                q.append('%spage:%s' % (PAGE_BASE, n))
    # --- write pages ---
    for clean, text in pages.items():
        fp = out_path(clean)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, 'wb') as f:
            f.write(text)
    # --- write assets (incl. assets referenced inside CSS via url(): fonts, bg images) ---
    to_fetch, done = set(assets), set()
    while to_fetch:
        a = to_fetch.pop()
        if a in done:
            continue
        done.add(a)
        try:
            # `a` is a decoded path (may contain spaces/special chars); re-encode for
            # the HTTP request, but write to the literal decoded path so the static
            # host serves it at the browser's percent-encoded URL.
            status, ctype, body = fetch('/' + urllib.parse.quote(a.lstrip('/')))
        except Exception as e:
            print('  asset SKIP', a, e); continue
        if status != 200:
            continue
        fp = os.path.join(OUT, a.lstrip('/'))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, 'wb') as f:
            f.write(body)
        if a.endswith('.css'):
            base_dir = posixpath.dirname(a)
            for u in re.findall(r'url\(\s*["\']?([^"\')]+)', body.decode('utf-8', 'replace')):
                u = urllib.parse.unquote(u.split('#')[0].split('?')[0].strip())
                if not u or u.startswith('data:') or u.startswith('http'):
                    continue
                full = posixpath.normpath(posixpath.join(base_dir, u))
                if full.startswith('/'):
                    to_fetch.add(full)
    # --- sitemap + rss verbatim ---
    for f_, name in [('/sitemap.xml', 'sitemap.xml'), ('/.rss', 'feed.xml')]:
        try:
            _, _, b = fetch(f_)
            with open(os.path.join(OUT, name), 'wb') as f:
                f.write(b)
        except Exception as e:
            print('  feed SKIP', f_, e)
    # --- _redirects (Cloudflare Pages): sections -> tag pages, .rss -> feed ---
    with open(os.path.join(OUT, '_redirects'), 'w') as f:
        for sec, tag in SECTIONS.items():
            f.write('%s %s%s/ 301\n' % (sec, TAX_BASE, slugify(tag)))
        f.write('/.rss /feed.xml 301\n')
    # --- _headers (Cloudflare Pages cache policy) ---
    # Cloudflare _headers COMBINES every matching rule's Cache-Control into one
    # header (it does not let the most-specific rule win), so a broad "/*" plus
    # per-asset rules yields a malformed doubled header. Use a single rule: always
    # revalidate. Pages purges its edge cache per deploy and browsers revalidate via
    # ETag (cheap 304s), so content is never stale after an update.
    with open(os.path.join(OUT, '_headers'), 'w') as f:
        f.write("/*\n  Cache-Control: public, max-age=0, must-revalidate\n")
        # RFC 8288 Link headers advertising agent-discovery resources.
        for lh in CFG.get('agent', {}).get('link_headers', []):
            parts = ['<%s>' % lh['href'], 'rel="%s"' % lh['rel']]
            if lh.get('type'):
                parts.append('type="%s"' % lh['type'])
            f.write('  Link: %s\n' % '; '.join(parts))
    # robots.txt is copied into OUT by the build script (build-static.sh)
    print('PAGES: %d | ASSETS: %d -> %s' % (len(pages), len(assets), OUT))


if __name__ == '__main__':
    main()

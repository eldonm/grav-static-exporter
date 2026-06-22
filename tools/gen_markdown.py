#!/usr/bin/env python3
"""
Agent-readiness markdown generation (run after the static export):

  * output/posts/<slug>/index.md   -- clean markdown per post (Grav source body),
                                       served on `Accept: text/markdown` by
                                       functions/_middleware.js (markdown-for-agents).
  * output/index.md                 -- homepage markdown (site intro + post list).
  * output/llms.txt                 -- agent-facing site index (llmstxt.org format),
                                       the target of the service-doc/describedby Link headers.

Site title/description come from static-export.config.json (site.title/description).

Usage: python3 tools/gen_markdown.py ./output [config.json]
"""
import sys, os, re
from export_config import load_config

OUT = sys.argv[1] if len(sys.argv) > 1 else 'output'
CFG = load_config(sys.argv[2] if len(sys.argv) > 2 else None)

POSTS_DIR = CFG['export']['posts_dir']
PROD      = CFG['site']['prod_url'].rstrip('/')
TITLE     = CFG['site'].get('title') or CFG['site']['host']
DESC      = CFG['site'].get('description') or ''
AG        = CFG.get('agent', {})


def parse_frontmatter(text):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', text, re.S)
    return (m.group(1), m.group(2)) if m else ('', text)


def yaml_scalar(fm, key):
    m = re.search(r'^%s:\s*(.+?)\s*$' % re.escape(key), fm, re.M)
    if not m:
        return ''
    v = m.group(1).strip()
    if (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].replace("''", "'")
    elif (v.startswith('"') and v.endswith('"')):
        v = v[1:-1]
    return v


def sort_key(date_ddmmyyyy):
    m = re.match(r'(\d{2})-(\d{2})-(\d{4})', date_ddmmyyyy or '')
    return (m.group(3) + m.group(2) + m.group(1)) if m else '00000000'


def collect_posts():
    posts = []
    if not os.path.isdir(POSTS_DIR):
        return posts
    for name in os.listdir(POSTS_DIR):
        src = os.path.join(POSTS_DIR, name, 'post.md')
        if not os.path.isfile(src):
            continue
        # only posts that were actually exported
        if not os.path.isfile(os.path.join(OUT, 'posts', name, 'index.html')):
            continue
        try:
            text = open(src, encoding='utf-8').read()
        except Exception:
            continue
        fm, body = parse_frontmatter(text)
        posts.append({
            'slug': name,
            'title': yaml_scalar(fm, 'title') or name,
            'date': yaml_scalar(fm, 'date'),
            'body': body.strip(),
        })
    posts.sort(key=lambda p: sort_key(p['date']), reverse=True)
    return posts


def first_paragraph(body):
    for para in re.split(r'\n\s*\n', body):
        t = re.sub(r'\s+', ' ', re.sub(r'[#>*_`\[\]()]', '', para)).strip()
        if len(t) > 40:
            return t[:200]
    return ''


def main():
    posts = collect_posts()

    # --- per-post markdown (for Accept: text/markdown negotiation) ---
    if AG.get('generate_markdown', True):
        for p in posts:
            d = os.path.join(OUT, 'posts', p['slug'])
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, 'index.md'), 'w', encoding='utf-8') as f:
                f.write('# %s\n\n' % p['title'])
                if p['date']:
                    f.write('*%s*\n\n' % p['date'])
                f.write(p['body'].rstrip() + '\n')
        # homepage markdown
        with open(os.path.join(OUT, 'index.md'), 'w', encoding='utf-8') as f:
            f.write('# %s\n\n' % TITLE)
            if DESC:
                f.write(DESC + '\n\n')
            f.write('## Posts\n\n')
            for p in posts:
                f.write('- [%s](/posts/%s/)%s\n' % (
                    p['title'], p['slug'], (' — %s' % p['date']) if p['date'] else ''))

    # --- llms.txt (agent site index; target of the Link headers) ---
    if AG.get('generate_llms_txt', True):
        with open(os.path.join(OUT, 'llms.txt'), 'w', encoding='utf-8') as f:
            f.write('# %s\n\n' % TITLE)
            if DESC:
                f.write('> %s\n\n' % DESC)
            f.write('Full site: %s\n\n' % PROD)
            f.write('## Posts\n\n')
            for p in posts:
                summary = first_paragraph(p['body'])
                f.write('- [%s](%s/posts/%s/)%s\n' % (
                    p['title'], PROD, p['slug'], (': ' + summary) if summary else ''))

    print('Markdown: %d posts + index.md + llms.txt -> %s' % (len(posts), OUT))


if __name__ == '__main__':
    main()

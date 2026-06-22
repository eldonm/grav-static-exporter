# grav-static-exporter

Turn a dynamic **Grav** (PHP) site into static HTML with client-side search and
ship it to **Cloudflare Pages** on every `git push`. No live PHP, no admin panel
on production — edit Grav locally, push, done.

Built for the [bootstrap5](https://github.com/getgrav/grav-theme-bootstrap5)
theme + the [simplesearch](https://github.com/getgrav/grav-plugin-simplesearch)
plugin out of the box, and adapts to other themes through one JSON config file.

## Why

A naive `wget --mirror` explodes on Grav's taxonomy/pagination: combinatorial
colon-param URLs (`/tag:ai/page:2`, `/archives_year:2022`) and cross-links blow
up into thousands of duplicate pages. This exporter instead crawls an **explicit
seed set** (sitemap pages + enumerated tags + archive years + sections),
discovers only bounded pagination, rewrites colon URLs to clean paths
(`/tag:ai` → `/tag/ai/`), captures assets (including fonts referenced inside
CSS), and swaps the now-dead server-side search for [Pagefind](https://pagefind.app).

## Pipeline

`tools/build-static.sh` orchestrates:

1. `docker build .` — build the Grav site image (your repo's `Dockerfile`).
2. Run it as a throwaway backend on `127.0.0.1`.
3. **`tools/static_export.py`** — crawl, rewrite colon URLs to clean paths,
   capture assets, emit `_redirects` + `_headers`.
4. **`tools/inject_pagefind.py`** — replace simplesearch with Pagefind (the main
   dialog becomes the live search UI; sidebar boxes become proxies that open it).
   Scopes the index to post bodies so listing pages don't create duplicate results.
5. `pagefind --site output` — build the search index.

Output lands in `output/`. The GitHub Actions workflow runs this and
`wrangler pages deploy`s it.

## Install (onboard a Grav site)

1. Copy into your Grav site's repo:
   - `tools/` → `tools/`
   - `examples/Dockerfile` → `Dockerfile` (repo root)
   - `examples/deploy-pages.yml` → `.github/workflows/deploy-pages.yml`
   - `static-export.config.example.json` → `static-export.config.json`
   - add `/output` and `__pycache__/` to `.gitignore` (see `examples/gitignore`)
2. Edit `static-export.config.json` (see **Configuration** below).
3. Create a Cloudflare Pages project (Direct Upload, name = your project) and add
   repo secrets `CLOUDFLARE_API_TOKEN` (permission: *Cloudflare Pages → Edit*) and
   `CLOUDFLARE_ACCOUNT_ID`.
4. Preview locally:
   ```bash
   bash tools/build-static.sh && (cd output && python3 -m http.server 8095)
   ```
5. Push to `main` → Actions builds + deploys. Add the custom domain in Pages
   (apex + `www`). Keep email DNS records **DNS-only**.

Requirements on the build machine / runner: Docker, Python 3 (stdlib only),
Node (for `npx pagefind`). GitHub's `ubuntu-latest` has all three.

## Configuration

All site/theme-specific values live in `static-export.config.json`.
`tools/export_config.py` deep-merges it over built-in defaults, so you only set
what differs from a stock Grav + simplesearch + bootstrap5 setup.

| Key | Meaning |
|-----|---------|
| `site.prod_url` / `site.host` | Production origin; the local Grav is crawled with this `Host` so absolute URLs render for prod. |
| `export.posts_dir` | Where post `.md` files live (tag/year enumeration reads frontmatter here). |
| `export.sections` | `"/route": "Tag Name"` — section pages that 302 to a tag page; emitted to `_redirects`. |
| `export.extra_seeds` | Extra routes to always export, e.g. `["/resume"]`. |
| `export.enumerate_tags` / `enumerate_archive_years` | Crawl a page per distinct tag / publish-year. Set `false` if N/A. |
| `export.taxonomy_param` / `taxonomy_base` | Taxonomy URL param + clean output base (`tag` → `/tag/`). |
| `export.pagination_base` | Clean base for listing pagination (`/posts/` → `/posts/page/2/`). |
| `export.archives_param` / `archives_base` | Archives-plugin param + clean output base. |
| `export.asset_prefixes` | Path roots treated as static assets to capture. |
| `pagefind.enabled` | `false` to skip search entirely. |
| `pagefind.form_attr` | Attribute marking the simplesearch `<form>`. |
| `pagefind.popup_id` | `id` of the main search dialog (becomes the live UI; others proxy to it). |
| `pagefind.post_path_prefix` | Output dir prefix identifying individual post pages (only these get indexed). |
| `pagefind.post_body` / `post_title` | `find`/`replace` to splice `data-pagefind-body` / `data-pagefind-meta` into post pages. |
| `pagefind.css` | `null` = built-in bootstrap5 "glass" styling; or a CSS string for another theme. |
| `deploy.cloudflare_pages_project` | Cloudflare Pages project name (the deploy workflow reads it via `jq`). |

**Same `bootstrap5` theme** → set `site.*`, `export.sections`, and
`deploy.cloudflare_pages_project`; the rest of the defaults just work.
**Different theme** → also adjust `pagefind.*` (form attribute, popup id, post
body/title `find` strings) and likely set `pagefind.css`. Inspect the theme's
search markup to get these.

## Agent readiness (optional)

The exporter also emits a few agent-discovery signals (honest ones for a static
content site — no fake API/OAuth/MCP):

- **`llms.txt`** + **homepage `index.md`** + a markdown twin per post
  (`/posts/<slug>/index.md`), generated by `tools/gen_markdown.py` from the Grav
  source. Set `site.title` / `site.description` in config.
- **RFC 8288 Link headers** in `_headers` (`service-doc` / `describedby` → `llms.txt`,
  RSS, sitemap). Configure via `agent.link_headers`.
- **Markdown for Agents** — copy `examples/functions/_middleware.js` to
  `functions/_middleware.js` at your repo root. It serves the markdown twin on
  `Accept: text/markdown` (with `Vary: Accept` + `x-markdown-tokens`); HTML stays
  default. Functions mode keeps `_headers`/`_redirects` working.
- **Content Signals** — add a `Content-Signal:` line under `User-agent: *` in your
  `robots.txt` (e.g. `Content-Signal: ai-train=no, search=yes, ai-input=yes`).

Toggle generation with `agent.generate_llms_txt` / `agent.generate_markdown`.

## Caveats (hard-won)

- **`_headers` is one rule.** Cloudflare Pages *combines* every matching `_headers`
  rule's `Cache-Control` into one header (the most-specific does **not** win), so
  overlapping rules emit a malformed doubled header. The exporter writes a single
  `/*` `max-age=0, must-revalidate` rule — Pages purges its edge per deploy and
  browsers revalidate via ETag, so content is never stale after an update.
- **Pagefind injection runs BEFORE indexing**, so the `data-pagefind-body` scope
  markers exist when `pagefind` runs. `build-static.sh` already orders it correctly.
- **Email DNS.** When you move the domain to Pages, only the apex + `www` records
  change. Keep MX/SPF/autoconfig records **DNS-only** — proxying them breaks email.
- **MPM.** The template `Dockerfile` forces Apache `mpm_prefork` (mod_php) and
  fails the build if more than one MPM loads. Keep it.

## License

MIT — see [LICENSE](LICENSE).

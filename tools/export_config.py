#!/usr/bin/env python3
"""
Shared config loader for the Grav -> Cloudflare Pages static export pipeline.

Reads `static-export.config.json` (repo root by default, or $STATIC_EXPORT_CONFIG)
and deep-merges it over the built-in DEFAULTS, so each site only overrides what
differs from a stock Grav + simplesearch + bootstrap5 setup. Stdlib only (json),
so it runs in the GitHub Actions runner without extra installs.

To onboard a new Grav site: copy `static-export.config.example.json` to
`static-export.config.json` and edit the handful of site-specific values
(see tools/README.md).
"""
import json
import os

# Built-in defaults == the original eldonmarks.com (bootstrap5 theme) behaviour,
# so an absent/partial config still produces the known-good output.
DEFAULTS = {
    "site": {
        # Absolute production origin; the local Grav is crawled with this Host so
        # absolute URLs render for production, and these get normalised to https.
        "prod_url": "https://example.com",
        "host": "example.com",
    },
    "export": {
        "posts_dir": "user/pages/01.posts",   # where post .md files live (for tag/year enumeration)
        "asset_prefixes": ["user", "images", "assets", "theme"],  # path roots treated as static assets
        "extra_seeds": [],                     # extra routes to always export, e.g. ["/resume"]
        "enumerate_tags": True,                # crawl a /<taxonomy>:<term> page per distinct tag
        "enumerate_archive_years": True,       # crawl a /<archives_param>:<year> page per distinct year
        "sections": {},                        # "/section-route": "Tag Display Name" (section 302s -> tag page)
        # Grav colon-param URL shapes -> clean output paths. Defaults match Grav's
        # taxonomy/pagination/archives-plugin conventions.
        "taxonomy_param": "tag",               # /tag:term  (also the frontmatter taxonomy key)
        "taxonomy_base": "/tag/",              # -> /tag/term/
        "pagination_base": "/posts/",          # bare /page:N -> /posts/page/N/
        "archives_param": "archives_year",     # /archives_year:YYYY
        "archives_base": "/archives/",         # -> /archives/YYYY/
    },
    "pagefind": {
        "enabled": True,
        "form_attr": "data-simplesearch-form", # marker on the simplesearch <form>
        "popup_id": "flq_popup_search",        # id of the main search dialog (becomes the live Pagefind UI)
        "post_path_prefix": "posts",           # output dir prefix that identifies individual post pages
        # Insert the Pagefind scoping attributes into post pages. find = exact substring,
        # replace = same substring with the attribute spliced in.
        "post_body": {
            "find": "<div class=\"flq-post-content",
            "replace": "<div data-pagefind-body class=\"flq-post-content",
        },
        "post_title": {
            "find": "<h1 class=\"display-5 mb-3\"",
            "replace": "<h1 data-pagefind-meta=\"title\" class=\"display-5 mb-3\"",
        },
        "css": None,   # None -> built-in bootstrap5 "glass" theme CSS (see inject_pagefind.py)
    },
    "deploy": {
        "cloudflare_pages_project": "",        # Pages project name (used by the deploy workflow)
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config_path(explicit=None):
    return (explicit
            or os.environ.get("STATIC_EXPORT_CONFIG")
            or "static-export.config.json")


def load_config(path=None):
    path = config_path(path)
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    return _merge(DEFAULTS, data)

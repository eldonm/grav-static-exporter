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
        # Used for the generated llms.txt / homepage markdown (agent readiness).
        "title": "",
        "description": "",
    },
    "export": {
        "posts_dir": "user/pages/01.posts",   # where post .md files live (for tag/year enumeration)
        "asset_prefixes": ["user", "images", "assets", "theme"],  # path roots treated as static assets
        # Downloadable page media (served at the page route, e.g. /posts/<slug>/file.pdf)
        # is captured by extension regardless of path prefix.
        "download_extensions": ["pdf", "zip", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
                                "csv", "txt", "rtf", "mp3", "mp4", "m4a", "mov", "webm", "epub"],
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
    # Agent-readiness features (RFC 8288 Link headers, llms.txt, markdown-for-agents).
    "agent": {
        "generate_llms_txt": True,             # write /llms.txt (agent-facing site index)
        "generate_markdown": True,             # write per-page .md + homepage index.md (Accept negotiation)
        "generate_agent_skills": True,         # write /.well-known/agent-skills/{index.json,*/SKILL.md}
        "webmcp": True,                         # register a WebMCP search tool (navigator.modelContext) on each page
        # RFC 8288 Link response headers emitted (via _headers) to advertise agent
        # resources. Defaults use registered relations (service-doc/describedby) that
        # point to real files, so they're honest for a static content site.
        "link_headers": [
            {"href": "/llms.txt", "rel": "service-doc"},
            {"href": "/llms.txt", "rel": "describedby"},
            {"href": "/feed.xml", "rel": "alternate", "type": "application/rss+xml"},
            {"href": "/sitemap.xml", "rel": "sitemap"},
        ],
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

#!/usr/bin/env python3
"""
Post-export step: replace simplesearch (server-side, dead on a static site) with
Pagefind client-side search across all exported HTML pages.

The theme-specific selectors (the simplesearch form attribute, the popup dialog
id, the post body/title markers) come from static-export.config.json so this
works on other Grav themes by editing config, not code. See tools/export_config.py.

Run BEFORE `pagefind --site output` (so the data-pagefind-body scoping applies):
    python3 tools/inject_pagefind.py ./output [config.json]
"""
import sys, os, re
from export_config import load_config

OUT = sys.argv[1] if len(sys.argv) > 1 else 'output'
CFG = load_config(sys.argv[2] if len(sys.argv) > 2 else None)

PF = CFG['pagefind']
WEBMCP     = CFG.get('agent', {}).get('webmcp', True)
SITE_TITLE = CFG.get('site', {}).get('title') or CFG.get('site', {}).get('host') or 'this site'
FORM_ATTR    = PF['form_attr']
POPUP_ID     = PF['popup_id']
POST_PREFIX  = PF['post_path_prefix']
POST_BODY    = PF['post_body']
POST_TITLE   = PF['post_title']

FORM_RE = re.compile(r'<form\s+name="search"[^>]*%s>.*?</form>' % re.escape(FORM_ATTR), re.S)
# the search form INSIDE the popup (the main dialog) -> becomes the real Pagefind UI
POPUP_FORM_RE = re.compile(
    r'(id="%s".*?)(<form\s+name="search"[^>]*%s>.*?</form>)' % (re.escape(POPUP_ID), re.escape(FORM_ATTR)),
    re.S)
SIMPLESEARCH_JS_RE = re.compile(r'<script[^>]*simplesearch[^>]*>\s*</script>', re.I)

PF_CONTAINER = '<div class="pf-search"></div>'

# Default Pagefind UI styling: matches the bootstrap5 theme's .flq-form-glass
# (translucent panel, magnifier on the right, X clear button on the input row).
# Override per-site via config pagefind.css when a different theme needs different chrome.
DEFAULT_PF_CSS = (
    '.pf-search{--pagefind-ui-primary:#fff;--pagefind-ui-text:#fff;'
    '--pagefind-ui-background:transparent;--pagefind-ui-border:transparent;'
    '--pagefind-ui-tag:rgba(255,255,255,.12);--pagefind-ui-border-width:0px;'
    '--pagefind-ui-border-radius:8px;--pagefind-ui-font:inherit;--pagefind-ui-scale:1;}'
    '.pf-search .pagefind-ui__search-input{'
    'background:hsla(0,0%,100%,.06);border:none;border-radius:8px;color:hsl(0,0%,90%);'
    'font-size:1.25rem;font-weight:400;line-height:1.5;padding:1rem 3.4rem 1rem 1.4rem;height:auto;}'
    '.pf-search .pagefind-ui__search-input:focus{background:hsla(0,0%,100%,.1);'
    'outline:none;box-shadow:none;}'
    '.pf-search .pagefind-ui__search-input::placeholder{color:hsl(0,0%,55%);}'
    '.pf-search .pagefind-ui__form::before{left:auto!important;right:22px!important;'
    'top:50%!important;transform:translateY(-50%);opacity:.7;}'
    '.pf-search .pagefind-ui__form:has(.pagefind-ui__search-input:not(:placeholder-shown))::before'
    '{display:none;}'
    '.pf-search .pagefind-ui__search-clear{position:absolute!important;right:18px;top:0;'
    'height:62px;display:flex;align-items:center;background:transparent;border:none;'
    'color:hsl(0,0%,65%);font-size:1.25rem;line-height:1;padding:0;cursor:pointer;z-index:10;}'
    '.pf-search .pagefind-ui__search-clear:hover{color:#fff;}'
    '.pf-search .pagefind-ui__result{border-top:1px solid hsla(0,0%,100%,.1);}'
    '.pf-search .pagefind-ui__result-title a,.pf-search .pagefind-ui__result-link{color:#fff;}'
    '.pf-search .pagefind-ui__result-excerpt{color:hsl(0,0%,72%);}'
    '.pf-search .pagefind-ui__message{color:hsl(0,0%,72%);}'
    '.pf-search mark{background:hsla(0,0%,100%,.85);color:#111;padding:0 .15em;}'
)
PF_HEAD = ('<link href="/pagefind/pagefind-ui.css" rel="stylesheet" />'
           '<style>' + (PF['css'] if PF['css'] else DEFAULT_PF_CSS) + '</style>')

# Non-popup search boxes become proxies that open the popup dialog and run the
# query there. __POPUP_ID__ is substituted with the configured dialog id.
PF_INIT = '''<script src="/pagefind/pagefind-ui.js"></script>
<script>
window.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".pf-search").forEach(function (el) {
    try {
      new PagefindUI({element: el, showSubResults: true, showImages: false,
        resetStyles: false, excerptLength: 25,
        translations: {placeholder: "Search ...", clear_search: "\\u2715"}});
    } catch (err) { console.error("PagefindUI init failed", err); }
  });
  // Sidebar/other search boxes are proxies: open the main popup dialog and run the query there.
  function pfOpenMain(q) {
    var t = document.querySelector('[data-fancybox][data-src="#__POPUP_ID__"]');
    if (t) { t.click(); }
    setTimeout(function () {
      var i = document.querySelector("#__POPUP_ID__ .pagefind-ui__search-input");
      if (i) { i.value = q || ""; i.focus(); i.dispatchEvent(new Event("input", {bubbles: true})); }
    }, 400);
  }
  document.querySelectorAll("form[data-pf-proxy]").forEach(function (f) {
    function go(e) { if (e) { e.preventDefault(); } var n = f.querySelector("input"); pfOpenMain(n && n.value); }
    f.addEventListener("submit", go);
    var inp = f.querySelector("input");
    if (inp) { inp.addEventListener("keydown", function (e) { if (e.key === "Enter") { go(e); } }); }
    var b = f.querySelector("button");
    if (b) { b.addEventListener("click", go); }
  });
});
</script>'''.replace('__POPUP_ID__', POPUP_ID)


# WebMCP: expose Pagefind site search as a browser-agent tool. Registers on load
# when navigator.modelContext is available; no-ops in browsers without WebMCP.
WEBMCP_SCRIPT = '''<script>
(function () {
  function reg() {
    var mc = navigator.modelContext;
    if (!mc || typeof mc.registerTool !== "function") return;
    try {
      mc.registerTool({
        name: "search_site",
        description: "Full-text search of __TITLE__ posts and pages.",
        inputSchema: {type: "object", properties: {query: {type: "string", description: "Search keywords"}}, required: ["query"]},
        execute: async function (input) {
          var pf = await import("/pagefind/pagefind.js");
          var s = await pf.search((input && input.query) || "");
          var top = await Promise.all(s.results.slice(0, 8).map(function (r) { return r.data(); }));
          return {content: top.map(function (d) {
            return {type: "text", text: (d.meta && d.meta.title ? d.meta.title : d.url) + "\\n" + location.origin + d.url + "\\n" + (d.excerpt || "")};
          })};
        }
      });
    } catch (e) { console.error("WebMCP registerTool failed", e); }
  }
  if (document.readyState !== "loading") reg();
  else document.addEventListener("DOMContentLoaded", reg);
})();
</script>'''.replace('__TITLE__', SITE_TITLE.replace('"', '\\"'))


def process(path):
    with open(path, encoding='utf-8') as f:
        html = f.read()
    if FORM_ATTR not in html and 'pf-search' not in html:
        return False
    # the popup's form becomes the live Pagefind UI; remaining (sidebar) search
    # forms become proxies that open the popup and forward the query.
    html = POPUP_FORM_RE.sub(lambda m: m.group(1) + PF_CONTAINER, html, count=1)
    html = html.replace(FORM_ATTR, 'data-pf-proxy')
    html = SIMPLESEARCH_JS_RE.sub('', html)
    # Index ONLY individual post pages, scoped to the article body, so listing pages
    # (home, tag, archives, pagination) don't duplicate every post's excerpt, and
    # nav/footer/sidebar chrome stays out of the index.
    rel = os.path.relpath(path, OUT)
    is_post = (rel.startswith(POST_PREFIX + os.sep)
               and not rel.startswith(os.path.join(POST_PREFIX, 'page') + os.sep))
    if is_post:
        html = html.replace(POST_BODY['find'], POST_BODY['replace'], 1)
        html = html.replace(POST_TITLE['find'], POST_TITLE['replace'], 1)
    if '/pagefind/pagefind-ui.css' not in html:
        html = html.replace('</head>', PF_HEAD + '\n</head>', 1)
    if '/pagefind/pagefind-ui.js' not in html:
        html = html.replace('</body>', PF_INIT + '\n</body>', 1)
    if WEBMCP and 'navigator.modelContext' not in html:
        html = html.replace('</body>', WEBMCP_SCRIPT + '\n</body>', 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return True


def main():
    if not PF['enabled']:
        print('Pagefind injection disabled in config'); return
    n = 0
    for root, _, files in os.walk(OUT):
        for fn in files:
            if fn.endswith('.html') and process(os.path.join(root, fn)):
                n += 1
    print('Pagefind injected into %d pages' % n)


if __name__ == '__main__':
    main()

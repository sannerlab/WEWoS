#!/usr/bin/env python3
# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Build the WEWoS documentation: docs/src/<page>.html -> docs/<page>.html.

    python3 docs/build_docs.py

Each source file holds one page's content (the inside of <main>), starting
with <h1>. This script wraps it in the shared layout: navigation, previous /
next links and footer (the layout of ADapt's documentation). The pages are
static HTML; open docs/index.html in a browser, or follow the "Docs" link of
a running WEWoS. The screenshots in docs/img/ are made by make_screenshots.py.
"""
import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')

# (file, navigation label, section)
PAGES = [
    ('index', 'Overview', 'Start here'),
    ('start', 'Getting started', 'Start here'),
    ('networks', 'Examples and open networks', 'Start here'),
    ('editor', 'Building a network', 'Start here'),
    ('running', 'Running a network', 'Start here'),
    ('tutorials', 'About the tutorials', 'Tutorials'),
    ('tut-first', 'Your first network', 'Tutorials'),
    ('tut-image', 'An image viewer', 'Tutorials'),
    ('tut-movie', 'Playing a series of images', 'Tutorials'),
    ('tut-macro', 'Indexing a list; macros', 'Tutorials'),
    ('tut-molecule', 'A virus capsid from one protomer', 'Tutorials'),
    ('tut-cage', 'An icosahedral cage', 'Tutorials'),
    ('tut-volumes', 'Volumes: isosurfaces and slices', 'Tutorials'),
    ('viewer', 'The 3D viewer', 'Viewing results'),
    ('colormap', 'Color maps and legends', 'Viewing results'),
    ('images', 'Images and plots', 'Viewing results'),
    ('files', 'Saving, opening, importing', 'Reference'),
    ('isolation', 'Execution modes', 'Reference'),
    ('libraries', 'Node libraries', 'Reference'),
    ('nodes', 'Writing your own nodes', 'Reference'),
    ('vision', 'WEWoS and Vision', 'Reference'),
    ('known-issues', 'Known issues', 'Reference'),
]

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} &middot; WEWoS documentation</title>
<link rel="stylesheet" href="style.css">
</head><body><div class="layout">
<nav class="side">
<a class="brand" href="index.html">WEWoS<small>Web Enabled Workflow System</small></a>
{nav}
</nav>
<main>
{content}
<div class="pn">{prev}{next}</div>
<footer class="page">WEWoS documentation. Author: Michel Sanner, PhD. Copyright &copy; 2026.
Every screenshot is of WEWoS itself, made by <code>docs/make_screenshots.py</code>. The tutorials
follow the Vision tutorial of MGLTools 1.5.3 (Michel Sanner and Guillaume Vareille, 2008).</footer>
</main></div></body></html>
"""


def nav(current):
    out, section = [], None
    for f, label, sec in PAGES:
        if sec != section:
            if section is not None:
                out.append('</ul>')
            out.append('<h4>%s</h4><ul>' % html.escape(sec))
            section = sec
        cls = ' class="here"' if f == current else ''
        out.append('<li><a%s href="%s.html">%s</a></li>' % (cls, f, html.escape(label)))
    out.append('</ul>')
    return '\n'.join(out)


def main():
    names = {f for f, _, _ in PAGES}
    for i, (f, label, sec) in enumerate(PAGES):
        with open(os.path.join(SRC, f + '.html')) as fh:
            content = fh.read().strip()
        m = re.search(r'<h1>(.*?)</h1>', content, re.S)
        title = re.sub('<[^>]+>', '', m.group(1)) if m else label
        prev = ('<a href="%s.html">&larr; %s</a>' % (PAGES[i - 1][0], html.escape(PAGES[i - 1][1]))
                if i else '<span></span>')
        nxt = ('<a href="%s.html">%s &rarr;</a>' % (PAGES[i + 1][0], html.escape(PAGES[i + 1][1]))
               if i + 1 < len(PAGES) else '<span></span>')
        page = TEMPLATE.format(title=title, nav=nav(f), content=content, prev=prev, next=nxt)
        with open(os.path.join(HERE, f + '.html'), 'w') as fh:
            fh.write(page)
        # every image a page names must exist, and every page it links to
        for img in re.findall(r'src="(img/[^"]+)"', content):
            if not os.path.isfile(os.path.join(HERE, img)):
                raise SystemExit('%s.html: missing %s' % (f, img))
        for link in re.findall(r'href="([\w-]+)\.html(?:#[\w-]+)?"', content):
            if link not in names:
                raise SystemExit('%s.html: link to a missing page %s.html' % (f, link))
    print('built %d pages in %s' % (len(PAGES), HERE))


if __name__ == '__main__':
    main()

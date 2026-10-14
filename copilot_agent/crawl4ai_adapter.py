"""Crawl4AI extraction without browser networking, caches, credentials or LLMs."""
from __future__ import annotations

from functools import lru_cache
from html import escape
from urllib.parse import urljoin

from .discovery_contracts import DiscoveryError
from .discovery_http import ReadFailure


@lru_cache(maxsize=1)
def strategy_type():
    try:
        from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
    except ImportError as error:
        raise ReadFailure('capability_unavailable') from error
    return LXMLWebScrapingStrategy


def extract_links(url, document, scope, limit=500):
    """Run the upstream extractor on a sanitized, bounded navigation document.

    The structural parser first rejects authentication. Passing a sanitized
    navigation document means upstream image metadata helpers,
    scripts, page text and attributes can never initiate extra reads or persist
    customer content. The pinned PublicReader remains the only network owner.
    """
    try:
        from lxml import html as lhtml
        tree = lhtml.fromstring(document, parser=lhtml.HTMLParser(no_network=True))
        # Preserve the observed document base, but validate every resulting URL
        # under the approved scope. No upstream media or page text is passed on.
        bases = tree.xpath('//base[@href]/@href')
        base = urljoin(url, bases[0]) if bases else url
        links, blocked, suppressed = set(), 0, 0
        for anchor in tree.iter('a'):
            href = anchor.get('href')
            if href is None:
                continue
            if len(links) >= limit:
                suppressed += 1
                continue
            try:
                links.add(scope.resolve(urljoin(base, href)).url)
            except DiscoveryError:
                blocked += 1
        html = '<html><body><nav>' + ''.join(
            '<a href="' + escape(link, quote=True) + '">navigation</a>'
            for link in sorted(links)) + '</nav></body></html>'
        result = strategy_type()().scrap(url, html, word_count_threshold=0,
                                        score_links=False, remove_forms=True)
        if not result.success:
            raise ReadFailure('capture_unavailable')
        candidates = result.links.internal + result.links.external
        return sorted({scope.resolve(link.href).url for link in candidates}), blocked, suppressed
    except ReadFailure:
        raise
    except Exception as error:
        # Library exceptions may contain page text/URLs; never export them.
        raise ReadFailure('capture_unavailable') from error

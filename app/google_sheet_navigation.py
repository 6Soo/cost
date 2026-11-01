"""Resolve exact tab titles from Google's read-only HTML tab index."""
import json
import re
import urllib.request

from .google_authority import SPREADSHEET_IDS, SourceError


def parse_tabs(markup):
    tabs = {}
    for name, gid in re.findall(
            r'items\.push\(\{name:\s*("(?:[^"\\]|\\.)*"),\s*pageUrl:\s*"(?:[^"\\]|\\.)*",\s*gid:\s*"(\d+)"', markup):
        # Google's JS strings use JSON escapes plus \xHH. Never execute page code.
        name = re.sub(r'\\x([0-9a-fA-F]{2})', r'\\u00\1', name)
        title = json.loads(name)
        if title in tabs and tabs[title] != gid:
            raise SourceError('SOURCE_TAB_AMBIGUOUS')
        tabs[title] = gid
    return tabs


def source_url(source, sheet):
    if source not in SPREADSHEET_IDS:
        raise SourceError('SOURCE_NOT_ALLOWED')
    base = 'https://docs.google.com/spreadsheets/d/' + SPREADSHEET_IDS[source]
    try:
        request = urllib.request.Request(base + '/htmlview', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError()
        gid = parse_tabs(data.decode('utf-8'))[sheet]
    except Exception:
        raise SourceError('SOURCE_TAB_UNAVAILABLE') from None
    return base + '/edit#gid=' + gid

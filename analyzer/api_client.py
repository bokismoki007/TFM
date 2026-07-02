import os
import re
import logging
import requests
import pandas as pd
from django.core.cache import cache
import hashlib

logger = logging.getLogger('analyzer.api_client')

WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
WIKI_REST_SEARCH = "https://en.wikipedia.org/w/rest.php/v1/search/page"

MISS_VALS = {'na', 'n/a', 'null', 'missing', 'unknown', 'none', 'nil', 'undefined', 'nan', '?', '-', '.', ''}

USER_AGENT = "AutoInsight/1.0 (https://example.com/autoinsight; opheliamcclaren@gmail.com) python-requests"

_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
})

REQUEST_TIMEOUT = 6


def clean_query(text):
    if not text or (isinstance(text, float) and pd.isna(text)):
        return None
    text = re.sub(r'[_\-]+', ' ', str(text).strip())
    text = re.sub(r'[^\w\s]', '', text)
    text = ' '.join(text.split())
    return None if text.lower() in MISS_VALS else text[:80]


def wiki_search(query):
    # primary: legacy action API (with proper User-Agent now)
    try:
        r = _session.get(
            WIKI_SEARCH,
            params={'action': 'query', 'list': 'search', 'srsearch': query, 'srlimit': 3, 'format': 'json'},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return [i['title'] for i in r.json().get('query', {}).get('search', [])]
        logger.warning("wiki_search action API returned %s for query=%r: %s", r.status_code, query, r.text[:200])
    except Exception as e:
        logger.warning("wiki_search action API failed for query=%r: %s", query, e)

    # fallback: modern REST search endpoint
    try:
        r = _session.get(WIKI_REST_SEARCH, params={'q': query, 'limit': 3}, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return [p['title'] for p in r.json().get('pages', [])]
        logger.warning("wiki_search REST API returned %s for query=%r: %s", r.status_code, query, r.text[:200])
    except Exception as e:
        logger.warning("wiki_search REST API failed for query=%r: %s", query, e)

    return []


def fetch_wiki_summary(title):
    try:
        r = _session.get(WIKI_SUMMARY.format(requests.utils.quote(title, safe='')), timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            logger.warning("fetch_wiki_summary returned %s for title=%r: %s", r.status_code, title, r.text[:200])
            return None
        d = r.json()
        return {
            'title': d.get('title', title),
            'description': d.get('description', ''),
            'extract': d.get('extract', '')[:600],
            'url': d.get('content_urls', {}).get('desktop', {}).get('page', '#'),
            'thumbnail': d.get('originalimage', {}).get('source') or d.get('thumbnail', {}).get('source'),
        }
    except Exception as e:
        logger.warning("fetch_wiki_summary failed for title=%r: %s", title, e)
        return None


def fetch_context(column_names, filename=''):
    cache_string = f"{filename}_{'_'.join(column_names[:4])}"
    cache_key = "wiki_" + hashlib.md5(cache_string.encode()).hexdigest()

    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    queries = []
    if filename:
        base = re.sub(r'[\._\-]+', ' ', os.path.splitext(filename)[0] if '.' in filename else filename)
        q = clean_query(base)
        if q:
            queries.append(q)
    for col in column_names[:4]:
        q = clean_query(col)
        if q and q not in queries:
            queries.append(q)

    results = []
    seen = set()
    for query in queries[:3]:
        for title in wiki_search(query)[:2]:
            if title in seen:
                continue
            seen.add(title)
            s = fetch_wiki_summary(title)
            if s and len(s.get('extract', '')) > 50:
                results.append(s)
            if len(results) >= 4:
                break
        if len(results) >= 4:
            break

    final_results = results if results else [{'error': 'No Wikipedia context found for this dataset.'}]
    cache.set(cache_key, final_results, 86400)
    return final_results
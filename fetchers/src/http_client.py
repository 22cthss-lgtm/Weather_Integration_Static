"""One bounded retry policy shared by Services; no adapter/product-level retries."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
import threading
import time
from urllib.parse import urlsplit, urljoin

import requests


class HttpFailure(requests.RequestException):
    pass


class SourceBudgetExceeded(HttpFailure):
    pass


def source_name(url):
    host = (urlsplit(url).hostname or '').lower()
    for source, suffixes in {
        'cwa': ('cwa.gov.tw',), 'jma': ('jma.go.jp',),
        'kma': ('kma.go.kr', 'weather.go.kr'), 'cimss': ('wisc.edu',),
        'nsidc': ('nsidc.org',),
    }.items():
        if any(host == suffix or host.endswith('.' + suffix) for suffix in suffixes):
            return source
    return host


class HttpPolicy:
    def __init__(self, *, max_requests=None, max_seconds=None, wait=time.sleep,
                 clock=time.monotonic, jitter=lambda: random.uniform(0, .5)):
        self.max_requests, self.max_seconds = max_requests, max_seconds
        self.wait, self.clock, self.jitter = wait, clock, jitter
        self.sources = {}
        self.lock = threading.Lock()

    def reserve(self, url):
        name = source_name(url)
        with self.lock:
            now = self.clock()
            state = self.sources.setdefault(name, {'start': now, 'count': 0, 'blocked': False})
            seconds = self.max_seconds or (240 if name == 'cwa' else 90)
            requests_limit = self.max_requests or (600 if name == 'cwa' else 80)
            remaining = seconds - (now - state['start'])
            if state['blocked'] or remaining <= 0 or state['count'] >= requests_limit:
                raise SourceBudgetExceeded('Source request/time budget exhausted')
            state['count'] += 1
            return remaining

    def pause(self, url, seconds):
        name = source_name(url)
        with self.lock:
            state = self.sources[name]
            limit = self.max_seconds or (240 if name == 'cwa' else 90)
            if self.clock() - state['start'] + seconds >= limit:
                state['blocked'] = True
                raise SourceBudgetExceeded('Source time budget exhausted')
        self.wait(seconds)

    def check_deadline(self, url):
        with self.lock:
            state = self.sources[source_name(url)]
            limit = self.max_seconds or (240 if source_name(url) == 'cwa' else 90)
            if self.clock() - state['start'] >= limit:
                state['blocked'] = True
                raise SourceBudgetExceeded('Source time budget exhausted')

    def get(self, url, *, transport=None, **kwargs):
        transport = transport or requests.get
        redirects = 0
        attempts = 0
        while True:
            remaining = self.reserve(url)
            options = dict(kwargs, allow_redirects=False)
            options['stream'] = True
            timeout = options.get('timeout', 15)
            # Split connect/read timeout so their combined allowance fits the
            # source deadline. requests is not a hard total-download deadline.
            if isinstance(timeout, (int, float)):
                options['timeout'] = min(timeout, max(.001, remaining / 2))
            else:
                options['timeout'] = tuple(min(t, max(.001, remaining / 2)) for t in timeout)
            response = None
            try:
                response = transport(url, **options)
                if isinstance(response, requests.Response):
                    self.check_deadline(url)
                code = response.status_code
                if isinstance(code, int) and code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    response.close()
                    redirects += 1
                    if not location or redirects > 5:
                        raise HttpFailure('Invalid source redirect')
                    target = urljoin(url, location)
                    if source_name(target) != source_name(url) or urlsplit(target).scheme != 'https':
                        raise HttpFailure('Source redirect is not permitted')
                    url = target
                    kwargs.pop('params', None)
                    continue
                if not isinstance(code, int) or code not in (408, 429, 500, 502, 503, 504):
                    if isinstance(response, requests.Response) and not kwargs.get('stream', False):
                        chunks, size = [], 0
                        for chunk in response.iter_content(chunk_size=16384):
                            self.check_deadline(url)
                            size += len(chunk)
                            if size > 16 * 1024 * 1024:
                                raise HttpFailure('Source response exceeds size limit')
                            chunks.append(chunk)
                        response._content = b''.join(chunks)
                        response._content_consumed = True
                        response.close()
                    return response
            except SourceBudgetExceeded:
                if response is not None:
                    response.close()
                raise
            except (requests.ConnectionError, requests.Timeout):
                if response is not None:
                    response.close()
            except requests.RequestException:
                if response is not None:
                    response.close()
                raise HttpFailure('Source request failed') from None
            attempts += 1
            if attempts >= 3:
                if response is not None:
                    response.close()
                # Stop fallback probes after repeated transport/server failure.
                with self.lock:
                    self.sources[source_name(url)]['blocked'] = True
                raise HttpFailure('Source request failed after limited retries') from None
            delay = (2, 5)[attempts - 1] + self.jitter()
            if response is not None:
                retry_after = response.headers.get('Retry-After')
                response.close()
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
            if delay > 30:
                with self.lock:
                    self.sources[source_name(url)]['blocked'] = True
                raise HttpFailure('Source retry delay exceeds this run limit') from None
            self.pause(url, delay)


_policy = ContextVar('weather_http_policy', default=None)


@contextmanager
def http_scope():
    token = _policy.set(HttpPolicy())
    try:
        yield
    finally:
        _policy.reset(token)


def http_get(url, *, session=None, **kwargs):
    policy = _policy.get() or HttpPolicy()
    return policy.get(url, transport=session.get if session is not None else requests.get, **kwargs)

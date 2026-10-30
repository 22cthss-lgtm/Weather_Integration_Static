"""Stable public-data identity. Check times are separate from source content."""
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .http_client import http_get
from .snapshots import read_resources

EXECUTION_FIELDS = frozenset(('fetched_at', 'updated_at', 'checked_at', 'attempted_at'))


def canonical_url(value):
    url = urlsplit(value)
    generated = {'_wi_content'}
    host = (url.hostname or '').lower()
    if host.endswith('.jma.go.jp'):
        generated.add('fetched')
    if host in ('tropic.ssec.wisc.edu', 'nsidc.org'):
        generated.add('ts')
    if host in ('www.cwa.gov.tw', 'cwa.gov.tw'):
        if url.path == '/Data/fcst_img/FI04.png':
            generated.add('t')
        if url.path.startswith('/Data/TCHP/'):
            generated.add('T')
    query = [(key, item) for key, item in parse_qsl(url.query, keep_blank_values=True) if key not in generated]
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), url.fragment))


def needs_image_hash(image):
    url = canonical_url(image['image_url'])
    return image.get('image_time') is None or '/winds/' in url or '/daily_images/' in url or '/FI04.png' in url


def images_in(value):
    if isinstance(value, dict):
        if 'image_url' in value:
            # Group representatives duplicate the first child; retain child order
            # in JSON identity, but download each canonical URL only once.
            yield value
        for child in value.values():
            yield from images_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from images_in(child)


def _semantic(value):
    if isinstance(value, dict):
        return {key: canonical_url(item) if key in ('image_url', 'source_url') else _semantic(item)
                for key, item in value.items() if key not in EXECUTION_FIELDS}
    if isinstance(value, list):
        return [_semantic(child) for child in value]
    return value


def stamp_changed_images(data, previous_hashes, current_hashes, checked_at):
    """Represent a changed fixed URL in public JSON without inventing image time."""
    for image in images_in(data):
        key = canonical_url(image['image_url'])
        digest = current_hashes.get(key)
        if needs_image_hash(image) and digest and digest != previous_hashes.get(key):
            url = urlsplit(image['image_url'])
            query = [(key, item) for key, item in parse_qsl(url.query) if key != '_wi_content']
            query.append(('_wi_content', digest))
            image['image_url'] = urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), url.fragment))
            image['fetched_at'] = checked_at
    return data


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def resource_identity(data, image_hashes=None):
    image_hashes = image_hashes or {}
    hashes = {canonical_url(image['image_url']): image_hashes.get(canonical_url(image['image_url']))
              for image in images_in(data) if needs_image_hash(image)}
    return _digest({'data': _semantic(data), 'images': hashes})


def content_metadata(data_root, image_hashes, created_at):
    resources, _ = read_resources(data_root)
    expected_urls = {canonical_url(image['image_url']) for content in resources.values()
                     for image in images_in(json.loads(content)) if needs_image_hash(image)}
    selected = {url: digest for url, digest in image_hashes.items() if url in expected_urls}
    if any(not re.fullmatch('[0-9a-f]{64}', digest) for digest in selected.values()):
        raise ValueError('Invalid image content digest')
    identities = {name: resource_identity(json.loads(raw), selected) for name, raw in resources.items()}
    return {'schema_version': 1, 'content_id': _digest(identities), 'content_created_at': created_at,
            'image_hashes': selected}


def verify_content(data_root, document):
    from .snapshots import exact, instant
    exact(document, {'schema_version', 'content_id', 'content_created_at', 'image_hashes'})
    if document['schema_version'] != 1 or type(document['image_hashes']) is not dict:
        raise ValueError('Invalid content identity')
    instant(document['content_created_at'], utc=True)
    expected = content_metadata(data_root, document['image_hashes'], document['content_created_at'])
    if expected != document:
        raise ValueError('Content identity mismatch')
    return document


def fetch_image_hashes(resources, previous=None):
    """Only fixed/unknown-time images need an extra content read; no body archive."""
    hashes = dict(previous or {})
    seen = set()
    for raw in resources.values():
        for image in images_in(json.loads(raw)):
            if not needs_image_hash(image):
                continue
            key = canonical_url(image['image_url'])
            # Duplicate representatives/children within one check share a request.
            if key in seen:
                continue
            seen.add(key)
            with http_get(image['image_url'], timeout=20, stream=True) as response:
                response.raise_for_status()
                if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                    raise ValueError('Image content hash response was not an image')
                digest, length = hashlib.sha256(), 0
                for chunk in response.iter_content(65536):
                    length += len(chunk)
                    if length > 16 * 1024 * 1024:
                        raise ValueError('Image exceeds hashing budget')
                    digest.update(chunk)
                if not length:
                    raise ValueError('Image content was empty')
                hashes[key] = digest.hexdigest()
    return hashes

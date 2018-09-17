from __future__ import print_function, unicode_literals

import concurrent.futures
import hashlib
import json
import logging
import os
import posixpath

import six


PYPI_PREFIX = 'https://pypi.org'

MAX_WORKERS = os.environ.get('PYTEST_PYPI_GATEWAY_MAX_THREAD')

logger = logging.getLogger('pytest.pypi-gateway')


class SimplePageParser(six.moves.html_parser.HTMLParser):
    """Parser to process a simple API page.
    """
    def __init__(self, *args, **kwargs):
        super(SimplePageParser, self).__init__(*args, **kwargs)
        self.links = {}
        self._current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            for key, value in attrs:
                if key.lower() == 'href':
                    url, qs = six.moves.urllib.parse.urldefrag(value)
                    hsh = six.moves.urllib.parse.parse_qs(qs)['sha256'][0]
                    self._current = (url, hsh)

    def handle_data(self, data):
        if self._current is not None:
            self.links[data] = self._current

    def handle_endtag(self, tag):
        if tag.lower() == 'a':
            self._current = None


def iter_filename_version(name):
    url = posixpath.join(PYPI_PREFIX, 'pypi', name, 'json')
    with six.moves.urllib.request.urlopen(url) as conn:
        data = conn.read()
    for version, infos in json.loads(data.decode('utf-8'))['releases'].items():
        for info in infos:
            yield info['filename'], version


def get_info(name):
    url = posixpath.join(PYPI_PREFIX, 'simple', name)
    with six.moves.urllib.request.urlopen(url) as conn:
        data = conn.read()
    parser = SimplePageParser()
    parser.feed(data.decode('utf-8'))
    versions = dict(iter_filename_version(name))
    return parser.links, versions


def get_file_hash(filename):
    sha256 = hashlib.sha256()
    with open(filename, 'rb') as f:
        while True:
            data = f.read(65535)
            if not data:
                break
            sha256.update(data)
    return 'sha256', sha256.hexdigest()


def mkdir_p(name):
    try:
        os.makedirs(name)
    except OSError as e:
        import errno
        if e.errno != errno.EEXIST:
            raise


def ensure_file(url, hsh, spec, filedir):
    filename = os.path.join(filedir, spec)
    if os.path.exists(filename):
        _, digest = get_file_hash(filename)
        if digest == hsh:
            logger.info('Skipping {}'.format(filename))
            return
        logger.warn('Replacing {}'.format(filename))
        os.unlink(filename)
    mkdir_p(os.path.dirname(filename))
    six.moves.urllib.request.urlretrieve(url, filename)
    logger.info('Downloaded {}'.format(filename))


def ensure_json(name, version, specs, jsondir):
    filename = os.path.join(jsondir, name, version, 'data.json')
    if os.path.exists(filename):
        logger.info('Skipping {}'.format(filename))
        return
    mkdir_p(os.path.dirname(filename))
    url = posixpath.join(PYPI_PREFIX, 'pypi', name, version, 'json')
    with six.moves.urllib.request.urlopen(url) as conn:
        pypi_data = json.loads(conn.read().decode('utf-8'))
    data = {
        'info': pypi_data['info'],
        'urls': [
            entry for entry in pypi_data['urls']
            if entry['filename'] in specs
        ],
    }
    with open(filename, 'w') as f:
        json.dump(data, f, ensure_ascii=True)
    logger.info('Generated {}'.format(filename))


def iter_ensure_package_files(exe, config, links, versions, filedir, jsondir):
    for name, specs in config.items():
        for spec in specs:
            try:
                url, hsh = links[spec]
            except KeyError:
                logger.warn('Failed to find link for {}'.format(spec))
                continue
            yield exe.submit(ensure_file, url, hsh, spec, filedir)
            try:
                version = versions[spec]
            except KeyError:
                logger.warn('Failed to find version for {}'.format(spec))
                continue
            yield exe.submit(ensure_json, name, version, set(specs), jsondir)


def ensure_packages(config, filedir, jsondir):
    links = {}
    versions = {}

    names = list(config)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        for name_links, name_versions in exe.map(get_info, names):
            links.update(name_links)
            versions.update(name_versions)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = list(iter_ensure_package_files(
            exe, config, links, versions, filedir, jsondir,
        ))
        for future in concurrent.futures.as_completed(futures):
            future.result()

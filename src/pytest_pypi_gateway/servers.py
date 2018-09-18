import collections
import json
import operator
import os

import bottle
import distlib.util
import distlib.version

from .packages import ensure_packages, get_file_hash


with open(os.environ['PYTEST_PYPI_GATEWAY_CONFIG_PATH']) as f:
    CONFIG = {
        distlib.util.normalize_name(k): v
        for k, v in json.load(f).items()
    }

STATIC_ROOT = os.path.abspath(os.environ['PYTEST_PYPI_GATEWAY_STATIC_ROOT'])

PACKAGES_DIR = os.path.join(STATIC_ROOT, 'f')
JSONDATA_DIR = os.path.join(STATIC_ROOT, 'd')


@bottle.route('/files/<filename>', name='package')
def package(filename):
    return bottle.static_file(
        filename, root=PACKAGES_DIR,
        mimetype='application/octet-stream', download=True,
    )


def _get_package_url(spec):
    path = bottle.url('package', filename=spec)
    return '{0.scheme}://{0.netloc}{1}'.format(bottle.request.urlparts, path)


@bottle.route('/simple/<name>', name='simple')
def simple_page(name):
    normalized_name = distlib.util.normalize_name(name)
    if name != normalized_name:
        bottle.redirect(bottle.url('simple', name=normalized_name), 301)
        return
    try:
        specs = CONFIG[name]
    except KeyError:
        bottle.abort(404)
        return
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Links for ',
        name,
        '</title></head><body><h1>Links for ',
        name,
        '</h1>',
    ]
    for spec in specs:
        digest = get_file_hash('sha256', os.path.join(PACKAGES_DIR, spec))
        parts.extend([
            '<a href="{}#sha256={}">'.format(_get_package_url(spec), digest),
            spec,
            '</a><br>',
        ])
    parts.append('</body></html>')
    return ''.join(parts)


def _as_version_or_none(s):
    try:
        return distlib.version.NormalizedVersion(s)
    except distlib.version.UnsupportedVersionError:
        return None


def _read_version_data(name, version):
    with open(os.path.join(JSONDATA_DIR, name, version, 'data.json')) as f:
        data = json.load(f)
    for entry in data['urls']:
        entry['url'] = _get_package_url(entry['filename'])
    return data


@bottle.route('/pypi/<name>/json', name='json')
@bottle.route('/pypi/<name>/<version_name>/json', name='json-version')
def json_page(name, version_name=None):
    normalized_name = distlib.util.normalize_name(name)
    if name != normalized_name:
        kwargs = {'name': normalized_name}
        if version_name is None:
            route = 'json'
        else:
            route = 'json-version'
            kwargs['version_name'] = version_name
        bottle.redirect(bottle.url(route, **kwargs), 301)
        return

    # This magic filters directories with valid version as names, and sort
    # them according in ascending order based on its parsed version value.
    version_names = [
        vername for vername, _ in sorted((
            (vername, version) for vername, version in (
                (vername, _as_version_or_none(vername))
                for vername in os.listdir(os.path.join(JSONDATA_DIR, name))
            ) if version is not None
        ), key=operator.itemgetter(-1))
    ]

    # Show latest version if not specified, mimicking PyPI.
    if version_name is None:
        version_name = version_names[-1]

    data = None
    releases = collections.OrderedDict()
    for vername in version_names:
        d = _read_version_data(name, vername)
        releases[vername] = d['urls']
        if vername == version_name:
            data = d
    if data is None:
        bottle.abort(404)

    data['releases'] = releases
    return data


def serve(**kwargs):
    ensure_packages(CONFIG, PACKAGES_DIR, JSONDATA_DIR)

    app = bottle.app()

    def strip_trailing_slash(environ, handler):
        if environ['PATH_INFO'].endswith('/'):
            environ['PATH_INFO'] = environ['PATH_INFO'][:-1]
        return app(environ, handler)

    bottle.run(app=strip_trailing_slash, **kwargs)

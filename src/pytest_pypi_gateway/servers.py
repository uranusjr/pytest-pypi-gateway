import json
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
        hash_type, digest = get_file_hash(os.path.join(PACKAGES_DIR, spec))
        parts.extend([
            '<a href="{}#{}={}">'.format(
                _get_package_url(spec), hash_type, digest,
            ),
            spec,
            '</a><br>',
        ])
    parts.append('</body></html>')
    return ''.join(parts)


def _as_version_or_zero(s):
    try:
        return distlib.version.NormalizedVersion(s)
    except distlib.version.UnsupportedVersionError:
        return distlib.version.NormalizedVersion('0dev0')


@bottle.route('/pypi/<name>/json', name='json')
@bottle.route('/pypi/<name>/<version>/json', name='json-version')
def json_page(name, version=None):
    normalized_name = distlib.util.normalize_name(name)
    if name != normalized_name:
        kwargs = {'name': normalized_name}
        if version is None:
            route = 'json'
        else:
            route = 'json-version'
            kwargs['version'] = version
        bottle.redirect(bottle.url(route, **kwargs), 301)
        return
    bottle.response.content_type = 'application/json'
    if version is None:
        version = max(
            os.listdir(os.path.join(JSONDATA_DIR, name)),
            key=_as_version_or_zero,
        )
    with open(os.path.join(JSONDATA_DIR, name, version, 'data.json')) as f:
        data = json.load(f)
    for entry in data['urls']:
        entry['url'] = _get_package_url(entry['filename'])
    return json.dumps(data, ensure_ascii=True)


def serve(**kwargs):
    ensure_packages(CONFIG, PACKAGES_DIR, JSONDATA_DIR)

    app = bottle.app()

    def strip_trailing_slash(environ, handler):
        if environ['PATH_INFO'].endswith('/'):
            environ['PATH_INFO'] = environ['PATH_INFO'][:-1]
        return app(environ, handler)

    bottle.run(app=strip_trailing_slash, **kwargs)

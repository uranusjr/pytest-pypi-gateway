import bottle


@bottle.route('/simple/<name>')
def simple_page(name):
    pass


@bottle.route('/pypi/<name>/json')
@bottle.route('/pypi/<name>/<version>/json')
def json_page(name, version=None):
    pass


def serve(**kwargs):
    app = bottle.app()

    def strip_trailing_slash(environ, handler):
        if environ['PATH_INFO'].endswith('/'):
            environ['PATH_INFO'] = environ['PATH_INFO'][:-1]
        return app(environ, handler)

    bottle.run(app=strip_trailing_slash, **kwargs)

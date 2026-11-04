"""WSGI entry point.

PythonAnywhere's own WSGI file should do:

    from wsgi import application

or, if the project is not on ``sys.path``:

    import sys; sys.path.insert(0, "/home/<user>/flight-tracker")
    from wsgi import application
"""

from app import create_app

application = create_app()

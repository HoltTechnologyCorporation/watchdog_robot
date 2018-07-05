MONGODB = {
    'connection': {},
    'dbname': 'watchdog',
}

try:
    from project.settings_local import *
except ImportError:
    pass

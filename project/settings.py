MONGODB = {
    'connection': {},
    'dbname': 'watchdog_robot',
}

try:
    from project.settings_local import *
except ImportError:
    pass

MONGODB = {
    'connection': {},
    'dbname': 'derminator',
}

try:
    from project.settings_local import *
except ImportError:
    pass

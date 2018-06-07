"""
Loads project's JSON files.

Dependencies: jsmin
"""

import os
import sys
import io
import json
import logging
from jsmin import jsmin # allows for json comments

__author__  = "Alexandros Nicolaides"
__status__  = "production"

log = logging.getLogger(__name__)

def load_settings(file_name):
    """ Loads user preferences from settings.json. """
    try:
        with io.open(CFG_DIR + file_name, mode='r', encoding="utf-8") as json_file:
            return json.loads(jsmin(json_file.read()))
        log.info('Loading \'' + file_name + '\' was successful.')
    except OSError as err:
        log.critical(err)
        log.warning('The program is about to abort operation.')
        sys.exit()

CFG_DIR = str(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'config/'))) + '/'
HEAD_DIR = str(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))) + '/'
USER_PREFS = load_settings('settings.json')
DB_PATH = HEAD_DIR + USER_PREFS['db.path']
TODOIST_SCHEMA = load_settings('todoist_schema.json')
ICONS = load_settings('icons.json')
DB_SCHEMA = load_settings('db_schema.json')
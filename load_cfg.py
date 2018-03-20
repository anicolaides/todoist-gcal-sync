"""
File: load_cfg.py
Purpose: Load project's JSON files.
Author: Alexandros Nicolaides
Dependencies: jsmin
"""

import sys
import io
import json
import logging
from jsmin import jsmin # allow for json comments

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

CFG_DIR = 'config/'
USER_PREFS = load_settings('settings.json')
TODOIST_SCHEMA = load_settings('todoist_schema.json')
ICONS = load_settings('icons.json')
DB_SCHEMA = load_settings('db_schema.json')
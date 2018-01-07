"""
File: load_cfg.py
Purpose: Load settings.json.
Author: Alexandros Nicolaides
Dependencies: jsmin
"""

import sys
import json
import logging
from jsmin import jsmin # allow for json comments

log = logging.getLogger(__name__)

def load_settings(file_name):
    """ Loads user preferences from settings.json. """
    try:
        with open(CFG_DIR + file_name, 'r') as json_file:
            return json.loads(jsmin(json_file.read()))
        log.info('Loading \'' + file_name + '\' was successful.')
    except OSError as err:
        log.critical(err)
        log.warning('The program is about to abort operation.')
        sys.exit()

CFG_DIR = 'config/'
USER_PREFS = load_settings('settings.json')

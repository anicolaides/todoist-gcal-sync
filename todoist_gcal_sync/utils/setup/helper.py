"""
Loads project's JSON files.

Dependencies: jsmin
"""

import os
import shutil
import sys
import io
import json
import logging
from jsmin import jsmin  # allows for json comments
from todoist_gcal_sync import gcal

__author__ = "Alexandros Nicolaides"
__status__ = "production"

log = logging.getLogger(__name__)

INSTALL_PATH = str(os.path.expanduser('~/.todoist-gcal-sync/'))
HEAD_DIR_PATH = str(os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir))) + '/'
CFG_DIR_PATH = str(HEAD_DIR_PATH + 'config/')

MAIL_SMTP_FILE_NAME = 'mail_smtp.json'
DB_FILE_NAME = 'data.db'


CREDS_DIR_PATH = INSTALL_PATH + '.credentials/'
LOGS_DIR_PATH = INSTALL_PATH + 'logs/'
DEBUG_LOG_FILE_PATH = LOGS_DIR_PATH + 'debug.log'
INFO_LOG_FILE_PATH = LOGS_DIR_PATH + 'info.log'
ERROR_LOG_FILE_PATH = LOGS_DIR_PATH + 'error.log'
DB_DIR_PATH = INSTALL_PATH + 'db/'
DB_PATH = DB_DIR_PATH + DB_FILE_NAME


def build_folder_higherarchy():
    """ Builds folder higherarchy of the daemon. """
    dirs = ['.credentials', 'logs', 'db']

    for dir_name in dirs:
        dir_path = INSTALL_PATH + dir_name
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path)
            except FileExistsError:
                log.warning(dir_name + " exists.")
            log.info('Initialization of folder higherarchy complete.')


def load_json(file_name, dir_path=CFG_DIR_PATH):
    """ Loads any JSON provided filename and dir path to file. """
    try:
        with io.open(dir_path + file_name, mode='r', encoding="utf-8") as json_file:
            return json.loads(jsmin(json_file.read()))
        log.info('Loading \'' + file_name + '\' was successful.')
    except OSError as err:
        log.critical(err)
        log.warning('The program is about to abort operation.')
        sys.exit()


def self_cleanup():
    """ Erases the data of the daemon. """
    if gcal.delete_cals():
        try:
            os.remove(DB_PATH)
            shutil.rmtree(LOGS_DIR_PATH)
        except OSError as err:
            log.error(
                str(err) + " Could not delete 'data.db', as part of the self cleanup process.")
            log.warning('The program is about to abort operation.')
            sys.exit()
        log.info('All data used by the daemon have been deleted.')


USER_PREFS = load_json('settings.json')
TODOIST_SCHEMA = load_json('todoist_schema.json')
ICONS = load_json('icons.json')
DB_SCHEMA = load_json('db_schema.json')

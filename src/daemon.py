"""
Interface of the daemon.

Dependencies: jsmin, schedule
"""

import os
import sys
sys.path.append("setup")
sys.path.append("auth")
import time
import logging
import shutil
import mylogging
import schedule
import load_cfg
import todo as todoist
import gcal
import gcal_sync
import requests
import urllib3
import signal
import sql_ops

__author__  = "Alexandros Nicolaides"

def signal_handler(signal, frame):
    log.critical("todoist-gcal-sync has aborted operation.")
    sys.exit()

def build_folder_higherarchy():
    """ Building the folder higherarchy of the daemon. """
    head_path = str(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))) + '/'
    dirs = ['credentials', 'config', 'logs', 'db']

    for dir_name in dirs:
        dir_path = head_path + dir_name
        if not os.path.exists(dir_path):
            try:
                os.mkdir(dir_path)
            except FileExistsError:
                log.critical('Could not create dir with name \'' + dir_name + '\'.')
            log.info('Directory with name \'' + dir_name + '\' has been created.')

def self_cleanup():
    """ Erases the data of the daemon. """
    cleanup = True
    reset_file = load_cfg.USER_PREFS['reset.file']

    if gcal.delete_cals():
        try:
            os.remove(load_cfg.DB_PATH)
            os.remove(reset_file)
            shutil.rmtree('logs/')
        except OSError as err:
            log.error(str(err) + " Could not delete 'data.db', as part of the self cleanup process.")
            log.warning('The program is about to abort operation.')
            sys.exit()
            cleanup = False
        log.info("'" + reset_file + "' has been deleted.")
        log.info('All data used by the daemon have been deleted.')
    return cleanup

def set_env_tz(todoist_user_tz):
    """ Set python timezone to todoist time, for schedule module to work properly. """

    os.environ['TZ'] = todoist_user_tz
    time.tzset()

def main():
    if os.path.exists(load_cfg.USER_PREFS['reset.file']) and self_cleanup():
        build_folder_higherarchy()
        sql_ops.init_db()

    set_env_tz(todoist.timezone())

    todoist.overdue()

    schedule.every().day.at("00:00").do(todoist.overdue)

    log.info('Entering syncing mode...')
    while True:
        schedule.run_pending()
        try:
            todoist.sync_todoist()
            gcal_sync.sync_gcal()
        except (TimeoutError, urllib3.exceptions.ReadTimeoutError, \
        requests.exceptions.ReadTimeout, OSError, urllib3.exceptions.ProtocolError, \
        requests.exceptions.ConnectionError, ConnectionResetError) as err:
            log.warning(err)
            time.sleep(load_cfg.USER_PREFS['daemon.connErrDelaySec'])

        time.sleep(load_cfg.USER_PREFS['daemon.refreshRateSec'])

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    log = logging.getLogger(__name__)
    build_folder_higherarchy()
    todoist.module_init()
    main()
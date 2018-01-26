"""
File: daemon.py
Purpose: Interface of the daemon.
Author: Alexandros Nicolaides
Dependencies: jsmin, schedule
"""

import os
import sys
import time
import logging
import shutil
import mylogging
import schedule
import load_cfg
import gcal
import todo
import requests
import urllib3

def folder_higherarchy():
    """ Building the folder higherarchy of the daemon. """

    dirs = ['credentials', 'config', 'logs', 'db']

    for directory in dirs:
        if not os.path.exists(directory):
            try:
                os.mkdir(directory)
            except FileExistsError as err:
                log.critical(err)
                log.warning('Could not create dir with name \'' + directory + '\'.')
            log.info('Directory with name \'' + directory + '\' has been successfully created.')

def self_cleanup(gcal_obj):
    """ Erases the data of the daemon. """

    db_path = 'db/data.db'
    reset_file = 'reset_daemon'

    if gcal_obj.delete_cals():
        try:
            os.remove(db_path)
        except OSError as err:
            log.error(str(err) + " Could not delete 'data.db', as part of the self cleanup process.")
            log.warning('The program is about to abort operation.')
            sys.exit()
        log.info('All data used by the daemon have been successfully deleted.')

        try:
            os.remove(reset_file)
            shutil.rmtree('logs/')
            log.info("'" + reset_file + "' has been successfully deleted.")
        except OSError as err:
            log.exception(err)

def main():
    my_gcal = gcal.Gcal()

    if os.path.exists('reset_daemon'):
        self_cleanup(my_gcal)

    my_todoist = todo.Todoist(load_cfg.USER_PREFS)

    # set python timezone to todoist time, for schedule module to work properly
    os.environ['TZ'] = my_todoist.todoist_user_tz

    time.tzset()

    my_todoist.sync.overdue()

    my_gcal.set_todoist_ref(my_todoist)

    schedule.every().day.at("00:00").do(my_todoist.sync.overdue)

    try:
        log.info('Entering syncing mode...')
        while True:
            schedule.run_pending()
            try:
                my_todoist.sync_todoist()
                my_gcal.sync_gcal()
            except (TimeoutError, urllib3.exceptions.ReadTimeoutError, \
            requests.exceptions.ReadTimeout, OSError, urllib3.exceptions.ProtocolError, \
            requests.exceptions.ConnectionError, ConnectionResetError) as err:
                log.warning(err)

            time.sleep(load_cfg.USER_PREFS['daemon.refreshRateSec'])
    except KeyboardInterrupt:
        log.debug('Keyboard interrupt.')

if __name__ == "__main__":
    folder_higherarchy()
    log = logging.getLogger(__name__)
    main()
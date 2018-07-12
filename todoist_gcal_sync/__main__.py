"""
Interface of the daemon.
"""
import logging
import os
import signal
import sys
import time

import requests
import schedule
import urllib3
import todoist_gcal_sync.gcal_sync as gcal_sync
import todoist_gcal_sync.todo as todoist
import todoist_gcal_sync.utils.setup.logger
from todoist_gcal_sync.utils.setup.helper import USER_PREFS
from todoist_gcal_sync.utils.setup.helper import build_folder_higherarchy


def signal_handler(signal, frame):
    """ Handles signals from the signal lib. """

    LOG.critical("todoist-gcal-sync has aborted operation.")
    sys.exit()


def set_env_tz(todoist_user_tz):
    """ Set python timezone to todoist time, for schedule module to work properly. """

    os.environ['TZ'] = todoist_user_tz
    time.tzset()


def main():
    """
        Daemon starting point.
    """
    todoist.overdue()

    schedule.every().day.at("00:00").do(todoist.overdue)

    LOG.info('Entering syncing mode...')
    while True:
        schedule.run_pending()
        try:
            todoist.sync_todoist()
            gcal_sync.sync_gcal()
        except (TimeoutError, urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ReadTimeout, OSError, urllib3.exceptions.ProtocolError,
                requests.exceptions.ConnectionError, ConnectionResetError) as err:
            LOG.warning(err)
            time.sleep(USER_PREFS['daemon.connErrDelaySec'])

        time.sleep(USER_PREFS['daemon.refreshRateSec'])


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    LOG = logging.getLogger(__name__)
    build_folder_higherarchy()
    set_env_tz(todoist.timezone())
    todoist.module_init()
    main()

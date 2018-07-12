"""
Authenticates Google Calendar.

Dependencies: google-api-python-client

Should Google change the auth process refer to:
https://developers.google.com/google-apps/calendar/quickstart/python

More info on the auth process here:
https://developers.google.com/google-apps/calendar/quickstart/python#step_1_turn_on_the_api_name
"""

import sys
import os
import logging

log = logging.getLogger(__name__)
__author__ = "Alexandros Nicolaides"
__status__ = "production"

try:
    from oauth2client import client
    from oauth2client import tools
    from oauth2client.file import Storage
except ImportError:
    log.critical('Please use \"pip3 install --upgrade google-api-python-client\" \
        to satisfy \"gcal_OAuth.py\" dependencies.')
    log.info('The program is about to abort due to an ImportError.')
    sys.exit()

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None

""" Should you need to modify any of the three constants below, delete your previously
saved credentials ~/.credentials/todoist_gcal_sync.json and re-authenticate.

All available authentication scopes can be found at:
https://developers.google.com/identity/protocols/googlescopes
"""

SCOPES = 'https://www.googleapis.com/auth/calendar'
CLIENT_SECRET_FILE = '../credentials/client_secret.json'
APPLICATION_NAME = 'todoist_gcal_sync'


def get_credentials():
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir, 'todoist_gcal_sync.json')

    store = Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
        flow.user_agent = APPLICATION_NAME
        if flags:
            credentials = tools.run_flow(flow, store, flags)
        log.info('Storing credentials to ' + credential_path)
    return credentials

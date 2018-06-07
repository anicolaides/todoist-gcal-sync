"""
Retrieves Todoist API token.

Dependencies:
"""

import os
import sys
import logging

log = logging.getLogger(__name__)
__author__  = "Alexandros Nicolaides"
__status__  = "production"

TODOIST_TOKEN_FILE_NAME = 'todoist_token'

class APItokenError(Exception):
    """
        Custom exception for API token errors.
    """
    pass

def retrieve_token(token_file_name):
    """
        Retrieves Todoist API token from file.
    """
    credentials_path = str(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, 'credentials/'))) + '/'
    with open(credentials_path + token_file_name, 'r') as token_file:
        try:
            api_token = token_file.readline().split(None, 1)[0]

            # testing token for validity, assuming token is alphanumeric
            if api_token and api_token.isalnum():
                log.info('API token from file \"' + token_file_name \
                    + '\" has been retrieved successfully.')
            else:
                raise APItokenError('The format of the API token retrieved from file \"' \
                    + token_file_name + '\" is not appropriate for use.')
        except (APItokenError, OSError) as err:
            log.critical(err)
            log.warning('The program is about to abort operation.')
            sys.exit()

    return api_token

todoist_api_token = retrieve_token(TODOIST_TOKEN_FILE_NAME)
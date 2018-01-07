"""
File: gcal_sync_handlers.py
Purpose: Handle syncing for Google Calendar.
Author: Alexandros Nicolaides
Dependencies: backoff
"""
import time
import logging
import requests
import backoff # exponential backoff
import load_cfg
from googleapiclient import errors
from gcal_OAuth import get_credentials


log = logging.getLogger(__name__)

class GcalSync:
    """ Synchronizes Google Calendar """

    def __init__(self, caller):
        self.__gcal = caller

    def fatal_code(self, e):
        expo_backoff = True

        if e.response.status_code == 400:
            """ 400: Bad Request """
            log.debug(e.response.reason)
        elif e.response.status_code == 401:
            """ 401: Invalid Credentials """
            # re-authenticate using OAuth flow
            gcal_creds = get_credentials()
            log.debug("An attempt to re-authenticate using OAuth flow was made, due to a 401 error.")
        elif e.response.status_code == 403:
            """ 403: Daily Limit Exceeded """
            if e.response.reason == 'dailyLimitExceeded':
                # pause application for 24 hours
                log.debug("Pausing application for a day, due to '403: Daily Limit Exceeded'.")
                time.sleep(86400)
            elif e.response.reason != 'dailyLimitExceeded':
                expo_backoff = False
        elif e.response.status_code == 404:
            """ 404: Not Found """
            expo_backoff = False
        elif e.response.status_code  == 500:
            """ 500: Backend Error """
            expo_backoff = False

        return expo_backoff

    @backoff.on_exception(backoff.expo,
                      requests.exceptions.HTTPError,
                      max_tries=10,
                      giveup=fatal_code)
    def cal_id(self, cal_id, sync_token):
        """
            Syncs each calendar using the "gcal_ids" table of the database.
        """
        nextSyncToken = None
        page_token = None
        while True:
            http_error = True
            events = None
            # no try-catch block used, becuase of expo backoff decorator
            events = self.__gcal.service.events().list(calendarId=cal_id, pageToken=page_token,\
                syncToken=sync_token, showDeleted=True).execute()
            http_error = False

            if events is not None and not http_error:
                if 'nextSyncToken' in events:
                    nextSyncToken = events['nextSyncToken']

                for event in events['items']:
                    log.debug(event['summary'])
                    task_id = self.__gcal.todoist.get_task_id(event['id'])
                    item = self.__gcal.todoist.api.items.get_by_id(task_id)

                    # we need to know the event_id of event that has just been moved to a diff project/calendar
                    # because the .move() func of Gcal simply performs a delete and insert operation for its .move()
                    # in order to prevent the task from being treated as deleted

                    # find the last icon used, out of all icons used to create an event
                    last_icon = None
                    event_name_substr = event['summary']
                    for char in event_name_substr.split():
                        if any(icon == char for icon in load_cfg.USER_PREFS['icons.eventSet']):
                            last_icon = char
                    event_name = event['summary'].split(last_icon, 1)[1].strip()

                    if item is not None and (event_name != item['content']):
                        priorities = ['p1', 'p2', 'p3', 'p4']
                        sentence = ''
                        parsed_priority = None
                        if any(priority == event_name.split()[-1] for priority in priorities):
                            # splits 'p#' to letter p and converts '#' to an int
                            parsed_priority = int(event_name.split()[-1][1])
                            word_list = event_name.split()
                            del word_list[-1]
                            for word in word_list:
                                sentence += word + ' '
                        else:
                            sentence = event_name

                        actual_priority = [4,3,2,1]

                        # this must be executed before elif event['updated']
                        if parsed_priority:
                            item.update(priority=actual_priority[parsed_priority-1])
                        item.update(content=sentence)
                        self.__gcal.todoist.api.commit()

                    if event['status'] == 'cancelled' and event['id'] != self.__gcal.todoist.changed_location_of_event:
                        # delete task from Todoist
                        if self.__gcal.todoist.delete_task(task_id):
                            log.info('Task with id: ' + str(task_id)  + ' has been deleted from Gcal and from Todoist.')
                    elif event['updated']:
                        # no try-catch block used, becuase of expo backoff decorator
                        new_event_date = event['start']['date']
                        self.__gcal.todoist.update_task_due_date(cal_id, event['id'], task_id, new_event_date)

                page_token = events.get('nextPageToken')
            if not page_token:
                break
        return nextSyncToken

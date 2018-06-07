"""
Sync handlers for Google Calendar (Gcal --> Todoist).

Dependencies:
"""

import time
import logging
import requests
import load_cfg
from googleapiclient import errors
from gcal_OAuth import get_credentials
import random
import simplejson
from gcal import service
import sql_ops
import todo as todoist

log = logging.getLogger(__name__)
__author__  = "Alexandros Nicolaides"
__status__  = "testing"


def cal_id(cal_id, sync_token):
    """
        Syncs each calendar using the "gcal_ids" table of the database.
    """
    nextSyncToken = None
    page_token = None
    while True:
        http_error = True
        events = None

        for n in range(0,5):
            try:
                events = service.events().list(calendarId=cal_id, pageToken=page_token,\
                    syncToken=sync_token, showDeleted=True).execute()
                http_error = False
                break
            except errors.HttpError as err:
                err = simplejson.loads(err.content)
                if any(error_code == err['error']['code'] for error_code in [403, 404, 500, 503]):
                    log.debug('Exponential backoff is being applied due to...\n' + str(err))
                    # exponential backoff
                    time.sleep((2 ** n) + random.randint(0, 1000) / 1000)
                else:
                    log.error(err)

        if events is not None and not http_error:
            if 'nextSyncToken' in events:
                nextSyncToken = events['nextSyncToken']

            for event in events['items']:
                log.debug(event['summary'])

                task_id = todoist.get_task_id(event['id'])
                # TODO WRONG
                item = todoist.get_task(task_id)

                # we need to know the event_id of event that has just been moved to a diff project/calendar
                # because the .move() func of Gcal simply performs a delete and insert operation for its .move()
                # in order to prevent the task from being treated as deleted

                # find the last icon used, out of all icons used to create an event
                last_icon = None
                event_name_substr = event['summary']
                for char in event_name_substr.split():
                    if any(icon == char for icon in load_cfg.ICONS['icons.eventSet']):
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
                    todoist.api.commit()

                if event['status'] == 'cancelled' and event['id'] != todoist.changed_location_of_event:
                    # delete task from Todoist
                    if task_id is not None and todoist.delete_task(task_id):
                        log.info('Task: ' + str(task_id)  + ' has been deleted from Gcal and from todoist.')
                elif event['updated']:
                    try:
                        new_event_date = event['start']['date']
                        if task_id is not None:
                            todoist.update_task_due_date(cal_id, event['id'], task_id, new_event_date)
                    except Exception as err:
                        log.error(err)
            page_token = events.get('nextPageToken')
        if not page_token:
            break
    return nextSyncToken

def sync_gcal():
    """ Updates Todoist to reflect Google Calendar changes. """

    cal_ids = sql_ops.select_from_where("calendar_id, calendar_sync_token", "gcal_ids", None, None, fetch_all=True)

    for i in range(0, len(cal_ids)):
        try:
            temp_token = cal_id(cal_ids[i][0], cal_ids[i][1])
        except requests.exceptions.HTTPError as err:
            log.debug(err)

        # update calendar_sync_token in "gcal_ids" table
        sql_ops.update_set_where("gcal_ids", "calendar_sync_token = ?", "calendar_id = ?", temp_token, cal_ids[i][0])

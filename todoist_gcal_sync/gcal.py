"""
Performs common operations on Google (Gcal <-- Todoist).

Dependencies: google-api-python-client
"""

import os.path
import sys
import logging
import time
import httplib2
from apiclient import discovery
from googleapiclient import errors
from todoist_gcal_sync.utils.auth.gcal_OAuth import get_credentials
from todoist_gcal_sync.utils.setup import helper as load_cfg
from todoist_gcal_sync.utils import sql_ops

log = logging.getLogger(__name__)
__author__ = "Alexandros Nicolaides"

gcal_creds = get_credentials()
http = gcal_creds.authorize(httplib2.Http())

# 'cache_discovery=False' is used to circumvent the file_cache issue for oauth2client >= 4.0.0
# More info on the issue here: https://github.com/google/google-api-python-client/issues/299
service = discovery.build('calendar', 'v3', http=http, cache_discovery=False)


def insert_event(calId, event_name, start_datetime=None, end_datetime=None, location=None, desc=None,
                 tz='America/Los_Angeles', color_id=None):
    event_id = None
    if end_datetime is None:
        end_datetime = start_datetime

    if calId is not None:
        """ Inserts event to Google Calendar. """
        event = {
            'summary': event_name,
            'location': location,
            'description': desc,
            'start': {
                'date': start_datetime,
                'timeZone': tz,
            },
            'end': {
                'date': end_datetime,
                'timeZone': tz,
            },
            "colorId": color_id,
            'reminders': {
                'useDefault': False,
                'overrides': load_cfg.USER_PREFS['events.reminder'],
            },
        }

        event = service.events().insert(calendarId=calId, body=event).execute()
        event_id = event['id']

    return event_id


def create_calendar(project_name, project_id, todoist_tz):
    cal_created = False
    cal_exists = False
    cal_project_name = 'Project: ' + project_name
    cal_id = None

    ''' Turns flag to True if calendar exists on Google's servers;
    Source :https://developers.google.com/google-apps/calendar/v3/reference/calendarList/list '''
    page_token = None
    while True:
        calendar_list = service.calendarList().list(pageToken=page_token).execute()
        for calendar_list_entry in calendar_list['items']:
            if calendar_list_entry['summary'] == cal_project_name:
                cal_exists = True
                cal_id = calendar_list_entry['id']
        page_token = calendar_list.get('nextPageToken')
        if not page_token:
            break

    ''' Creates Google Calendar with Todoist project name (if calendar does not exist). '''
    if not cal_exists:
        calendar = {
            'summary': cal_project_name,
            'timeZone': todoist_tz
        }

        try:
            created_calendar = service.calendars().insert(body=calendar).execute()

            cal_row = [cal_project_name,
                       created_calendar['id'], project_id, None, ]

            if sql_ops.insert_many("gcal_ids", cal_row):
                log.info("'" + cal_project_name + "'" + ' has been created.')
                cal_created = True
        except errors.HttpError as err:
            log.exception(err._get_reason)
            time.sleep(1)
            sys.exit("The daemon is about to abort operation.")
    else:
        if os.path.exists('/data.db'):
            ''' Case where calendar id is missing from database '''
            already_in_db = False

            # Check if calendar found on Google's server is missing from 'gcal_ids' table
            # cursor = conn.execute("SELECT calendar_id from gcal_ids")
            cursor = sql_ops.select_from_where("calendar_id", "gcal_ids")
            for row in cursor:
                if row[0] == cal_id:
                    already_in_db = True
                    break

            if not already_in_db:
                cal_row = [cal_project_name, cal_id, project_id, None, ]
                if sql_ops.insert_many("gcal_ids", cal_row):
                    log.info(cal_project_name +
                             "\' has been added to the database.")
            else:
                log.warning(cal_project_name + '\' already exists.')
    return cal_created


def update_event_date(cal_id, event_id, new_date=None, event_name=None, color_id=None, extended_date=None):
    # 1) Updates event date
    # 2) Updates event name
    op_code = False
    if cal_id and event_id:
        update_needed = False
        # First retrieve the event from the API.
        event = None
        try:
            event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        except Exception as err:
            log.exception(
                str(err) + "\nEvent requested could not be retrieved.")

        if event:
            if new_date:
                event['start']['date'] = new_date
                event['end']['date'] = new_date
                event['colorId'] = color_id
                update_needed = True
            elif extended_date:
                event['end']['date'] = extended_date
                event['colorId'] = color_id
                update_needed = True
            if event_name:
                update_needed = True
                event['summary'] = event_name

            if update_needed:
                try:
                    service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
                    op_code = True
                except Exception as err:
                    log.exception(str(err))

    return op_code


def delete_calendar(cal_id=None):
    deletion = True
    try:
        if cal_id:
            service.calendars().delete(calendarId=cal_id).execute()
    except Exception as err:
        log.exception(err)
        deletion = False
    return deletion


def delete_cals():
    calendars_deleted = True
    try:
        data = sql_ops.select_from_where(
            "calendar_name, calendar_id", "gcal_ids", fetch_all=True)

        # delete all calendars created by the daemon, from Google Calendar
        for row in data:
            # row[0] is the id of the calendar to be deleted
            if row[1]:
                if (delete_calendar(row[1])):
                    log.info(row[0] + '\' calendar has been deleted.')
                    sql_ops.delete_from_where(
                        "gcal_ids", "calendar_id", row[1])
                else:
                    log.error('\'' + row[0] + '\' could not be deleted.')
            else:
                calendars_deleted = False
                log.error('Calendar id provided for deletion is not correct.')
    except Exception as err:
        log.exception(err)

    return calendars_deleted


def delete_event(cal_id, event_id):
    op_code = False
    try:
        service.events().delete(calendarId=cal_id, eventId=event_id).execute()
        op_code = True
    except Exception as err:
        log.exception(str(err) + ' Event could not be deleted.')

    return op_code


def update_event_color(cal_id, event_id, color_id=None):
    op_code = True

    if cal_id and event_id:
        # None turns the event to it's default color id
        event = None
        try:
            # retrieve event from Gcal
            event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        except Exception as err:
            log.exception(str(
                err) + 'Could not retrieve event from Google API, to perform color change on it.')
            op_code = False

        if event:
            event['colorId'] = color_id

            try:
                service.events().update(calendarId=cal_id,
                                        eventId=event_id, body=event).execute()
            except Exception as err:
                log.exception('Although the color of the event was retrieved,'
                              + ' we could not update the color of the event.')
                op_code = False

    return op_code


def update_event_summary(cal_id=None, event_id=None, event_name=None):
    op_code = True
    if cal_id and event_id and event_name:
        # retrieve event from Gcal
        event = None
        try:
            event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        except Exception as err:
            log.exception(
                str(err) + 'Could not retrieve event from Google API, to perform color change.')
            op_code = False

        if event:
            event['summary'] = event_name

            try:
                service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
            except Exception as err:
                log.exception('Could not update the name of the event.')
                op_code = False

    return op_code


def update_event_location(cal_id, event_id, location, dest_cal_id=None):
    op_code = True
    event = None

    try:
        # retrieve event from Google Calendar API
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        if event:
            event['location'] = location
    except Exception as err:
        log.exception(err)
        op_code = False

    try:
        if event:
            service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
    except Exception as err:
        log.exception(err)
        op_code = False

    if dest_cal_id != cal_id:
        try:
            service.events().move(calendarId=cal_id, eventId=event_id,
                                  destination=dest_cal_id).execute()
        except Exception as err:
            log.exception(err)

    return op_code


def update_event_desc(cal_id, event_id, desc):
    op_code = True

    event = None
    try:
        # retrieve event from Google Calendar API
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        if event:
            event['description'] = desc
    except Exception as err:
        log.exception(err)
        op_code = False

    try:
        if event:
            service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
    except Exception as err:
        log.exception(err)
        op_code = False

    return op_code


def update_event_name(cal_id, event_id, event_name):
    if cal_id and event_id:
        event = None
        try:
            event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        except Exception as err:
            log.exception('Could not retrieve the event from Gcal.')
        if event:
            log.info(event + ' name has been updated.')


def update_event_reminders(cal_id, event_id, minutes_reminder=None):
    op_code = True
    if cal_id and event_id:
        event = None

        try:
            event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        except Exception as err:
            log.exception(err)
            op_code = False

        if not minutes_reminder:
            event['reminders'] = None
        else:
            event['reminders']['useDefault'] = False
            event['reminders']['overrides'] = [
                {'method': 'popup', 'minutes': minutes_reminder}]

        try:
            service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
        except Exception as err:
            log.exception(str(err))
            op_code = False

    return op_code


def update_cal_name(cal_id, new_cal_name):
    cal_name_updated = True
    calendar = None
    new_cal_name = 'Project: ' + new_cal_name

    if cal_id and new_cal_name:
        try:
            calendar = service.calendars().get(calendarId=cal_id).execute()
        except Exception as err:
            log.exception(err)
            cal_name_updated = False

        if calendar:
            calendar['summary'] = new_cal_name

            try:
                service.calendars().update(calendarId=cal_id, body=calendar).execute()
            except Exception as err:
                log.exception(str(err))
                cal_name_updated = False

    return cal_name_updated

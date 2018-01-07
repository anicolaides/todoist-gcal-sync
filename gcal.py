"""
File: gcal.py
Purpose: Handle Google Calendar operations.
Author: Alexandros Nicolaides
Dependencies: google-api-python-client
"""

from gcal_OAuth import get_credentials
import httplib2
from apiclient import discovery
import datetime
from googleapiclient import errors
import os.path
import sqlite3
import sys
import logging
import time
import load_cfg
from gcal_sync_handlers import GcalSync
import requests

log = logging.getLogger(__name__)

class Gcal:
    """ Handles all operations for Google Calendar. """
    gcal_creds = get_credentials()
    http = gcal_creds.authorize(httplib2.Http())

    # 'cache_discovery=False' is used to circumvent the file_cache issue for oauth2client >= 4.0.0
    # More info on the issue here: https://github.com/google/google-api-python-client/issues/299
    service = discovery.build('calendar', 'v3', http=http, \
        developerKey='ENTER YOUR DEVELOPER KEY HERE', cache_discovery=False)

    def __init__(self, todoist_obj_ref=None):
        self.sync = GcalSync(self)
        self.todoist = todoist_obj_ref

    def insert_event(self, calId, event_name, datetime=None, location=None, desc=None, \
        tz='America/Los_Angeles', color_id=None):

        """ Inserts event to Google Calendar. """
        event = {
            'summary': event_name,
            'location': location,
            'description': desc,
            'start': {
                'date': datetime,
                'timeZone': tz,
            },
            'end': {
                'date': datetime,
                'timeZone': tz,
            },
            "colorId": color_id,
            'reminders': {
                'useDefault': False,
                'overrides': load_cfg.USER_PREFS['events.reminder'],
            },
        }

        if calId:
            event = Gcal.service.events().insert(calendarId=calId, body=event).execute()
        return event['id']

    def create_calendar(self, project_name, project_id, todoist_tz):
        cal_exists = False
        cal_project_name = 'Project: ' + project_name
        cal_id = None

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS gcal_ids
                (calendar_name integer, calendar_id integer, todoist_project_id integer, calendar_sync_token text)''')

            ''' Turns flag to True if calendar exists on Google's servers;
            Source :https://developers.google.com/google-apps/calendar/v3/reference/calendarList/list '''
            page_token = None
            while True:
                calendar_list = Gcal.service.calendarList().list(pageToken=page_token).execute()
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
                    created_calendar = Gcal.service.calendars().insert(body=calendar).execute()

                    cal_for_project_info = [cal_project_name,
                                            created_calendar['id'], project_id, None,]
                    c.executemany('INSERT INTO gcal_ids VALUES (?,?,?,?)',
                                (cal_for_project_info,))

                    conn.commit()

                    log.info("'" + cal_project_name + "'" + ' has been created.')
                except errors.HttpError as err:
                    log.exception(err._get_reason)
                    time.sleep(1)
                    sys.exit("The daemon is about to abort operation.")
            else:
                if os.path.exists('/data.db'):
                    ''' Case where calendar id is missing from database '''
                    already_in_db = False

                    # Check if calendar found on Google's server is missing from 'gcal_ids' table
                    cursor = conn.execute("SELECT calendar_id from gcal_ids")
                    for row in cursor:
                        if row[0] == cal_id:
                            already_in_db = True

                    if not already_in_db:
                        cal_for_project_info = [cal_project_name, cal_id, project_id, None,]
                        c.executemany('INSERT INTO gcal_ids VALUES (?,?,?,?)',
                                    (cal_for_project_info,))

                        conn.commit()
                        log.info(cal_project_name + "\' has been added to the database.")
                    else:
                        log.warning(cal_project_name + '\' already exists.')

        conn.close()

    def sync_cal_deletion(self):
        """ Delete info of calendar that got deleted from Google's server. """
        pass

    def update_event_date(self, cal_id, event_id, new_date=None, event_name=None, color_id=None, extended_date=None):
        # 1) Updates event date
        # 2) Updates event name
        op_code = False
        if cal_id and event_id:
            update_needed = False
            # First retrieve the event from the API.
            event = None
            try:
                event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            except Exception as err:
                log.exception(str(err) + "\nEvent requested could not be retrieved.")

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
                        Gcal.service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
                        op_code = True
                    except Exception as err:
                        log.exception(str(err))

        return op_code

    def delete_calendar(self, cal_id=None):
        deletion = True
        try:
            if cal_id:
                calendar = Gcal.service.calendars().delete(calendarId=cal_id).execute()
        except Exception as err:
            log.exception(err)
            deletion = False
        return deletion

    def delete_cals(self):
        op_code = True

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            try:
                cursor = conn.execute("SELECT calendar_name, calendar_id FROM gcal_ids")

                # delete all calendars created by the daemon, from Google Calendar
                for row in cursor:
                    # row[0] is the id of the calendar to be deleted
                    if row[1]:
                        if (self.delete_calendar(row[1])):
                            log.info(row[0] + '\' calendar has been deleted.')
                            try:
                                c.execute(
                                    '''DELETE FROM gcal_ids WHERE calendar_id = ?''', (row[1],))
                            except Exception as err:
                                log.error(err)
                        else:
                            log.error('\'' + row[0] + '\' could not be deleted.')
                    else:
                        op_code = False
                        log.error('Calendar id provided for deletion is not correct.')

                conn.commit()
            except Exception as err:
                log.exception(err)

        conn.close()

        return op_code

    def delete_event(self, cal_id, event_id):
        op_code = False
        try:
            Gcal.service.events().delete(calendarId=cal_id, eventId=event_id).execute()
            op_code = True
        except Exception as err:
            log.exception(str(err) + ' Event could not be deleted.')

        return op_code

    def update_event_color(self, cal_id, event_id, color_id=None):
        op_code = True

        if cal_id and event_id:
            # None turns the event to it's default color id
            event = None
            try:
                # retrieve event from Gcal
                event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            except Exception as err:
                log.exception(str(err) + 'Could not retrieve event from Google API, to perform color change on it.')
                op_code = False

            if event:
                event['colorId'] = color_id

                try:
                    updated_event = Gcal.service.events().update(calendarId=cal_id, \
                    eventId=event_id, body=event).execute()
                except Exception as err:
                    log.exception('Although the color of the event was retrieved,'
                    + ' we could not update the color of the event.')
                    op_code = False

        return op_code

    def update_event_summary(self, cal_id=None, event_id=None, event_name=None):
        op_code = True
        if cal_id and event_id and event_name:
            # retrieve event from Gcal
            event = None
            try:
                event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            except Exception as err:
                log.exception(str(err) + 'Could not retrieve event from Google API, to perform color change.')
                op_code = False

            if event:
                event['summary'] = event_name

                try:
                    Gcal.service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
                except Exception as err:
                    log.exception('Could not update the name of the event.')
                    op_code = False

        return op_code

    def update_event_location(self, cal_id, event_id, location, dest_cal_id=None):
        op_code = True

        event = None
        updated_event = None

        try:
            # retrieve event from Google Calendar API
            event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            if event:
                event['location'] = location
        except Exception as err:
            log.exception(err)
            op_code = False

        try:
            if event:
                Gcal.service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
        except Exception as err:
            log.exception(err)
            op_code = False

        if dest_cal_id != cal_id:
            try:
                updated_event = Gcal.service.events().move(calendarId=cal_id, eventId=event_id,destination=dest_cal_id).execute()
            except Exception as err:
                log.exception(err)

        return op_code

    def update_event_desc(self, cal_id, event_id, desc):
        op_code = True

        event = None
        updated_event = None

        try:
            # retrieve event from Google Calendar API
            event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            if event:
                event['description'] = desc
        except Exception as err:
            log.exception(err)
            op_code = False

        try:
            if event:
                Gcal.service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
        except Exception as err:
            log.exception(err)
            op_code = False

        return op_code

    def update_event_name(self, cal_id, event_id, event_name):
        if cal_id and event_id:
            event = None
            try:
                event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            except Exception as err:
                log.exception('Could not retrieve the event from Gcal.')
            if event:
                log.info(event + ' name has been updated.')

    def update_event_reminders(self, cal_id, event_id, minutes_reminder=None):
        op_code = True
        if cal_id and event_id:
            event = None

            try:
                event = Gcal.service.events().get(calendarId=cal_id, eventId=event_id).execute()
            except Exception as err:
                log.exception(err)
                op_code = False

            if not minutes_reminder:
                event['reminders'] = None
            else:
                event['reminders']['useDefault'] = False
                event['reminders']['overrides'] =  [{ 'method': 'popup', 'minutes': minutes_reminder}]

            try:
                updated_event = Gcal.service.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
            except Exception as err:
                log.exception(str(err))
                op_code = False

        return op_code

    def sync_gcal(self):
        """ Updates Todoist to reflect Google Calendar changes. """

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute("SELECT calendar_id, calendar_sync_token FROM gcal_ids")

            cal_ids = c.fetchall()

            for i in range(0, len(cal_ids)):
                try:
                    temp_token = self.sync.cal_id(cal_ids[i][0], cal_ids[i][1])
                except requests.exceptions.HTTPError as err:
                    log.debug(err)

                # update calendar_sync_token in "gcal_ids" table
                c.execute("UPDATE gcal_ids SET calendar_sync_token = ? WHERE calendar_id = ?",
                            (temp_token, cal_ids[i][0],))

                conn.commit()

        conn.close()

    def set_todoist_ref(self, todoist_obj_ref):
        self.todoist = todoist_obj_ref
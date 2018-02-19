"""
File: todo.py
Purpose: Handle Todoist operations.
Author: Alexandros Nicolaides
Dependencies: jsonschema, todoist-python, pytz, python-dateutil
"""

import todoist # todoist-python module
import os
from gcal import Gcal
import sqlite3
from datetime import datetime, timedelta
import pytz
import json
from jsonschema import exceptions
from jsonschema import validate
import time
import dateutil.parser
import todoist_auth
from todoist_sync_handlers import TodoistSync
import logging

log = logging.getLogger(__name__)

class Todoist:
    """ All operations related to Todoist. """

    api = todoist.TodoistAPI(todoist_auth.todoist_api_token)

    def __init__(self, settings, todoist_schema):
        self.todoist_schema = todoist_schema
        self.settings = settings
        self.gcal = Gcal(self)
        initial_sync = Todoist.api.sync() # needed to initialize 3 vars below
        self.sync = TodoistSync(self)
        self.todoist_user_tz = self.sync.timezone()
        self.premium_user = Todoist.api.user.state['user']['is_premium']
        self.inbox_project_id = Todoist.api.user.state['user']['inbox_project']
        self.changed_location_of_event = None

        # TODO: add icons to be assiciated with labels variable

        # if db exists, skip first time initialization
        if os.path.exists('db/data.db'):
            # to prevent losing sync data when the daemon shuts down
            self.sync_todoist(initial_sync)
        else:
            if settings['projects.standalone']:
                self.standalone_projects()
            if settings['projects.excluded']:
                self.exclude_projects()
            self.data_init()

    def data_init(self):
        """
            Data initialization of Todoist (db/data.db).
        """
        self.write_sync_db(Todoist.api.sync())

        self.projects_gcal()

        if self.premium_user:
            self.init_completed_tasks()

        for item in Todoist.api.items.all(self.has_due_date_utc):
            # Todoist task --> Gcal event
            self.sync.new_task_added(item)

        log.debug("Pausing operation for 20s, to prevent reaching Todoist's user limits due to " \
        + "initialization utilizing massive amount of requests.")
        time.sleep(20)

    def projects_gcal(self):
        """ Create a calendar for each Todoist project, taking into consideration
        'excluded_ids' and 'standalone_ids' table.
        """
        self.sync.timezone()

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            # create a calendar for each parent project, excluding project 'Inbox'
            for project in Todoist.api.projects.all():
                standalone_project = False

                # search for project in "excluded_ids"
                try:
                    c.execute("SELECT project_id FROM excluded_ids WHERE project_id = ?", \
                        (project['id'],))
                except sqlite3.OperationalError as err:
                    log.debug(err)

                if c.fetchone():
                    log.info('The project \'' + Todoist.api.projects.get_by_id(
                    project['id'])['name'] + '\' is beeing excluded.')

                # if not excluded
                else:
                    # search for project in 'standalone_ids'
                    try:
                        c.execute("SELECT project_id from standalone_ids WHERE project_id = ?", \
                            (project['id'],))
                    except Exception as err:
                        log.debug(err)

                    if c.fetchone():
                        standalone_project = True

                    # for a standalone project, the project cannot be excluded or archived
                    # create calendar for parent or standalone projects
                    if not project['is_archived'] and (project['indent'] == 1 \
                        and project['name'] != 'Inbox') or (project['indent'] != 1 \
                        and project['name'] != 'Inbox' and standalone_project):
                        self.gcal.create_calendar(project['name'], project['id'], self.todoist_user_tz)

    def exclude_projects(self):
        excluded_projects = []
        for project_name in self.settings['projects.excluded']:
            for project in Todoist.api.projects.all():
                if project_name == project['name']:
                    excluded_projects.append(project)

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS excluded_ids
                (project_name TEXT, project_id integer, parent_project_id integer )''')

            # populate lists with the properties of each excluded project
            excluded_indents = []
            excluded_ids = []
            for project in excluded_projects:
                excluded_indents.append(project['indent'])
                excluded_ids.append(project['id'])

            # sort lists to have parent projects first
            keydict = dict(zip(excluded_ids, excluded_indents))
            excluded_ids.sort(key=keydict.get)

            # insert row of data to 'excluded_ids'
            for project_id in excluded_ids:
                # search for project in the 'standalone_ids'
                try:
                    c.execute("SELECT project_id FROM standalone_ids WHERE project_id = ?", \
                        (project_id,))
                except sqlite3.OperationalError as err:
                    log.debug(err)

                if c.fetchone():
                    log.info('Project \'' + Todoist.api.projects.get_by_id(project_id) \
                        ['name'] + '\' is a standalone project, thus cannot be excluded.')

                # if not a standalone project, process further
                else:
                    parent_id = self.__parent_project_id__(project_id)

                    try:
                        c.execute("SELECT project_id FROM excluded_ids WHERE project_id = ?", \
                            (parent_id,))
                    except sqlite3.OperationalError as err:
                        log.exception(err)

                    # if parent project is already excluded
                    if c.fetchone():
                        log.info('The parent project of the project to be excluded is already \
                            excluded.')
                    else:
                        """ Case where sub-projects of parent project to be excluded have been excluded.
                        """
                        try:
                            c.execute("SELECT parent_project_id FROM excluded_ids WHERE \
                                parent_project_id = ?", (project_id,))
                        except sqlite3.OperationalError as err:
                            log.exception(err)

                        sub_projs_removed = True
                        if c.fetchone():
                            try:
                                # remove sub-projects of parent project
                                c.execute('''DELETE FROM excluded_ids WHERE parent_project_id = ?''', \
                                    (project_id,))
                                conn.commit()
                            except sqlite3.OperationalError as err:
                                log.warning(err)
                                sub_projs_removed = False

                            if sub_projs_removed:
                                """ 1.delete calendar from gcal service
                                    2.remove all the tasks with the project_id of calendar from db
                                    3.insert project to 'excluded_ids'
                                """
                                try:
                                    c.execute("SELECT calendar_id FROM gcal_ids WHERE \
                                        todoist_project_id = ?", (project_id,))
                                    calendar_id = c.fetchone()[0]

                                    if self.gcal.delete_calendar(calendar_id):
                                        tasks_deleted = True
                                        try:
                                            c.execute('''DELETE FROM todoist WHERE \
                                                parent_project_id = ?''', (project_id,))
                                        except sqlite3.OperationalError as err:
                                            tasks_deleted = False
                                            log.exception(err)

                                        if tasks_deleted:
                                            try:
                                                c.execute('''DELETE FROM gcal_ids WHERE \
                                                    todoist_project_id = ?''', (project_id,))
                                            except sqlite3.OperationalError as err:
                                                log.warning(err)

                                            c.execute("INSERT INTO excluded_ids VALUES (?,?,?)", \
                                                (Todoist.api.projects.get_by_id(project_id)['name'],
                                                project_id, parent_id,))

                                            log.info('The project with name \'' \
                                            + Todoist.api.projects.get_by_id(project_id)['name'] + \
                                            '\' has been added to the \'excluded_ids\' table.')

                                        conn.commit()
                                except sqlite3.OperationalError as err:
                                    log.warning(err)
                        else:
                            c.execute("INSERT INTO excluded_ids VALUES (?,?,?)", \
                                (Todoist.api.projects.get_by_id(project_id)['name'], project_id, \
                                parent_id,))
                            log.info('The project with name \'' + Todoist.api.projects.get_by_id(
                                project_id)['name'] + '\' has been added to the \'excluded_ids\' table.')

                            conn.commit()

        conn.close()

    def standalone_projects(self):
        standalone_projects = []
        for project_name in self.settings['projects.standalone']:
            for project in Todoist.api.projects.all():
                if project_name == project['name']:
                    standalone_projects.append(project)

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS standalone_ids
                (project_name TEXT, project_id integer )''')

            for project in standalone_projects:
                try:
                    c.execute("SELECT project_id FROM excluded_ids WHERE project_id = ?", \
                        (project['id'],))
                except sqlite3.OperationalError:
                    # ignore error because of 'no such table: excluded_ids'
                    pass

                if c.fetchone():
                    log.info('The project with name \'' + project['name'] + '\' is being excluded, \
                        thus cannot become a standalone project.')
                else:
                    # if not excluded
                    parent_project_id = self.__parent_project_id__(project['id'])
                    parent_proj_excluded = True

                    if not self.settings['projects.excluded']:
                        parent_proj_excluded = False
                    else:
                        try:
                            c.execute("SELECT project_id FROM excluded_ids WHERE project_id = ?", \
                                (parent_project_id,))
                        except sqlite3.OperationalError:
                            # ignore error because of 'no such table: excluded_ids'
                            parent_proj_excluded = False

                    if not parent_proj_excluded and project['indent'] != 1:
                        c.execute("INSERT INTO standalone_ids VALUES (?,?)", (project['name'], \
                            project['id'],))

                        conn.commit()
                    else:
                        log.info('The parent project of ' + project['name'] + ' is already marked \
                            as a standalone project.')
        conn.close()

    def sync_todoist(self, initial_sync=None):
        # indicates the event was just moved
        self.changed_location_of_event = None

        write_to_db = True

        # retrieve last api.sync() from database
        prev_sync_resources = self.read_json_db()
        prev_sync_token = None
        if prev_sync_resources:
            prev_sync_token = prev_sync_resources['sync_token']

        new_api_sync = None
        new_api_sync_token = None

        if not initial_sync:
            """ each call to api.sync() changes sync_token in cache, used for incremental syncing
            ~/.todoist-sync/your_api_key.sync
            """
            # force a sync to obtain last changes, since last api.sync()
            new_api_sync = Todoist.api.sync()
        else:
            new_api_sync = initial_sync

        # case where Todoist sync is an empty string
        while new_api_sync == '':
            new_api_sync = Todoist.api.sync()

        # Pauses until a valid Todoist API sync response is retrieved
        while not self.is_post_response_valid(new_api_sync)[0] or not self.is_post_response_valid(new_api_sync)[1]:
            if not self.is_post_response_valid(new_api_sync)[1]:
                if new_api_sync['error_tag'] == 'LIMITS_REACHED':
                    log.critical('LIMITS_REACHED from Todoist; pausing operation for 8s...')
                    time.sleep(8)
            new_api_sync = Todoist.api.sync()

        changes = []
        note_changes = []
        if new_api_sync:
            new_api_sync_token = new_api_sync['sync_token']

            # was there a change between this and last api.sync() ?
            if prev_sync_token != new_api_sync_token:
                changes = new_api_sync['items']
                note_changes = new_api_sync['notes']

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            # if anything changed since last sync, then
            # for each changed item, perform the following operations
            for i in range(0, len(changes)):
                task_id = changes[i]['id']

                c.execute("SELECT project_id, parent_project_id, due_date, event_id FROM todoist \
                    WHERE task_id = ?", (task_id,))

                task_data = c.fetchone()

                if task_data:
                    event_id = task_data[3]

                    calendar_id = self.find_task_calId(task_data[0], task_data[1])

                    if changes[i]['due_date_utc']:
                        if calendar_id and task_data:

                            recurring_task_completed = False
                            if 'every' in changes[i]['date_string'].lower() and self.premium_user:

                                try:
                                    # give some time for Todoist's servers to update activity log
                                    time.sleep(2)

                                    last_activity = Todoist.api.activity.get()

                                    # determine if recurring task was completed or got postponed
                                    if last_activity:
                                        for k in range(0, len(last_activity)):
                                            if last_activity[k]['object_id'] == task_id:
                                                if last_activity[k]['event_type'] == 'completed':
                                                    recurring_task_completed = True
                                                # break on first instance where last_activity[k]['object_id'] == task_id
                                                break
                                except Exception as err:
                                    log.exception(err)

                            if changes[i]['is_deleted']:
                                try:
                                    if self.sync.deletion(calendar_id, event_id, task_id):
                                        log.info('Task with id: ' +  task_id + ' has been successfully deleted.')
                                except Exception as err:
                                    write_to_db = False
                                    log.exception(err)
                            elif recurring_task_completed and self.premium_user:
                                c.execute("SELECT project_id, parent_project_id, due_date, event_id  FROM todoist WHERE task_id = ?",
                                    (task_id,))

                                data_recurring = c.fetchone()
                                recurring_task_due_date = None
                                if data_recurring:
                                    recurring_task_due_date = data_recurring[2]

                                if recurring_task_due_date != changes[i]['due_date_utc']:
                                    if recurring_task_completed:
                                        try:
                                            if self.sync.checked(calendar_id, event_id, task_id, recurring_task_due_date):
                                                log.debug(str(task_id) + ': recurring task was checked.')
                                        except Exception as err:
                                            write_to_db = False
                                            log.exception(str(err) + 'Could not mark the task with id: ' \
                                                + str(task_id) + ' as completed rec.')

                                        if self.sync.new_task_added(changes[i]):
                                            log.debug('Task id ' + str(task_id) \
                                                + ' has been added to Gcal for the next date of the recurring task.')
                                        else:
                                            write_to_db = False
                                            log.error('Task id: ' +  str(task_id)
                                            + ' could not be added to Google Calendar, '
                                            + 'for the next date of the recurring task being completed.')
                            else:
                                # Task due date --> Gcal date (sync)
                                if changes[i]['due_date_utc'] and changes[i]['project_id'] \
                                    and task_data and changes[i]['due_date_utc'] != task_data[2]:

                                    try:
                                        self.sync.date_google(calendar_id, changes[i]['due_date_utc'], \
                                            task_id, changes[i]['content'], event_id)
                                    except Exception as err:
                                        write_to_db = False
                                        log.error(str(err) + 'Could not update date of event in Gcal...')

                                # Task name --> Event name (sync)
                                try:
                                    self.sync.task_name(calendar_id, event_id, task_id)
                                except Exception as err:
                                    write_to_db = False
                                    log.error(err)

                                # Task checked --> Gcal (sync)
                                # needs to be called after task name sync,
                                # for task with due date in the future to have a tick and be moved to today
                                if changes[i]['checked']:
                                    try:
                                        self.sync.checked(calendar_id, event_id, task_id)
                                    except Exception as err:
                                        write_to_db = False
                                        log.error(str(err) + ' Could not mark the task with id: ' \
                                            + str(task_id) + ' as completed from task checked.')

                                # Task location --> Gcal (sync)
                                if task_id and self.sync.task_location(calendar_id, event_id, task_id, changes[i]['project_id']):
                                    log.info(str(task_id) + ' has been moved to a different project.')
                                else:
                                    write_to_db = False

                    else:
                        # remove event from Gcal
                        try:
                            if self.sync.deletion(calendar_id, event_id, task_id ):
                                log.info('Task with id: ' + str(task_id) + ' has been deleted successfully.')
                        except Exception as err:
                            write_to_db = False
                            log.error(str(err))
                elif not changes[i]['checked']:
                    """ Undo operation detected. """
                    if self.is_completed(task_id):
                        self.sync.undo(task_id)

                    # task with due date has not been deleted
                    elif changes[i]['due_date_utc']:
                        try:
                            self.sync.new_task_added(changes[i])
                        except Exception as err:
                            write_to_db = False
                            log.exception('task id: ' + str(task_id) \
                                + ' could not be added to Google Calendar.')

            # for each note changed, perform the following operations
            for j in range(0, len(note_changes)):

                # Task note added --> gcal desc (sync)
                if note_changes[j]['item_id']:
                    self.sync.update_desc_location(note_changes[j]['item_id'])
            if write_to_db:
                self.write_sync_db(new_api_sync)

        conn.close()

    def write_sync_db(self, json_str=None):
        if json_str:
            conn = sqlite3.connect('db/data.db')

            with conn:
                c = conn.cursor()

                c.execute('''CREATE TABLE IF NOT EXISTS todoist_sync (api_dot_sync text, \
                    sync_token integer)''')

                # truncate table each time, before inserting data
                try:
                    c.execute('''DELETE FROM todoist_sync''')

                    conn.commit()
                except Exception as err:
                    log.exception(err)

                # combine row of data
                todoist_json_info = [json.dumps(json_str), json_str['sync_token'], ]

                c.executemany('INSERT INTO todoist_sync VALUES (?,?)', (todoist_json_info,))

                conn.commit()

            conn.close()
        else:
            log.warning('Nothing was provided to be synched.')

    def read_json_db(self):
        last_sync_json = None

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute("SELECT api_dot_sync, sync_token FROM todoist_sync")

            try:
                # fetches and places each one in a list
                json_data = c.fetchone()

                if json_data:
                    last_sync = json_data[0]

                    last_sync_json = json.loads(last_sync)
            except Exception as err:
                log.exception(str(err) + 'Could not retrieve the data from todoist_sync database.')
        return last_sync_json

    def get_task_id(self, event_id):
        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute("SELECT task_id FROM todoist WHERE event_id = ?",(event_id,))

            task_id = c.fetchone()

            if task_id:
                task_id = task_id[0]

        return task_id

    def delete_task(self, task_id):
        op_code = True

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            if task_id:
                item = Todoist.api.items.get_by_id(task_id)
                if item is not None:
                    item.delete()
                    Todoist.api.commit()

                    # if task is found in the 'todoist' table
                    try:
                        c.execute('''DELETE FROM todoist WHERE task_id = ?''', (task_id,))

                        conn.commit()
                    except Exception as err:
                        log.exception(err)
                        op_code = False
        conn.close()

        return op_code

    def update_task_due_date(self, cal_id, event_id, task_id, new_event_date):
        todoist_tz = pytz.timezone(self.sync.timezone())
        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute("SELECT due_date FROM todoist WHERE task_id = ?", (task_id,))

            due_date = c.fetchone()
            if due_date:
                # turn google date to todoist utc date
                due_date = due_date[0]
                new_due_date = self.parse_google_date(new_event_date)
                new_due_date = new_due_date.replace(hour=21, minute=59, second=59)
                new_due_date = new_due_date.isoformat()

                try:
                    item = Todoist.api.items.get_by_id(task_id)
                    item.update(due_date_utc=str(new_due_date))
                    Todoist.api.commit()
                except Exception as err:
                    log.error(err)

                event_name = self.sync.event_name(item)
                try:
                    self.gcal.update_event_date(cal_id, event_id, None, event_name , None)
                except Exception as err:
                    log.error(err)

                try:
                    task_due_date = self.__todoist_utc_to_date__(item['due_date_utc'])
                except Exception as err:
                    log.exception(err)

                difference = (task_due_date - datetime.now(todoist_tz).date()).days

                # if task is not overdue and task was overdue previously
                if difference >= 0 and not self.is_overdue(task_id):
                    self.gcal.update_event_color(cal_id,event_id,None)
                else:
                    self.gcal.update_event_color(cal_id,event_id,11)

                c.execute("UPDATE todoist SET due_date = ? WHERE task_id = ?", \
                    (item['due_date_utc'],task_id,))
                conn.commit()

        conn.close()

    def init_completed_tasks(self):
        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            completed_task = Todoist.api.completed.get_all(limit=200)['items']

            for k in range(0, len(completed_task)):
                task_id = None
                item = None
                valid_completed_task = True
                valid_item = True

                try:
                    validate(completed_task[k], self.todoist_schema['completed_item'])
                except:
                    valid_completed_task = False

                if valid_completed_task:
                    # Todoist task --> Gcal event adds them to the day they were completed
                    task_id = completed_task[k]['task_id']

                    item = Todoist.api.items.get(task_id)
                    if item is not None:
                        try:
                            item = item['item']
                            validate(item, self.todoist_schema['items'])
                        except:
                            valid_item = False

                        try:
                            if valid_item and item['due_date_utc'] and completed_task[k]['completed_date'] \
                             and self.sync.new_task_added(item, completed_task[k]['completed_date']):

                                # grab the data from the db to supply them to the sync.checked func
                                # attempt to retrieve the data for the task using the "todoist" table
                                c.execute("SELECT project_id, parent_project_id, event_id FROM todoist WHERE task_id = ?", \
                                    (task_id,))

                                task_data = c.fetchone()

                                if task_data:
                                    event_id = task_data[2]

                                    calendar_id = self.find_task_calId(task_data[0], task_data[1])

                                    self.sync.checked(calendar_id,event_id,task_id, True)
                        except Exception as err:
                            log.exception(err)

    ########### Retrieval functions ###########
    def find_cal_id(self, project_id, parent_id):
        conn = sqlite3.connect('db/data.db')

        cal_id = None
        with conn:
            c = conn.cursor()

            task_project_cal_id = None
            task_parent_cal_id = None

            c.execute("SELECT calendar_id FROM gcal_ids WHERE todoist_project_id = ?", \
                (project_id,))

            # check if standalone project of calendar exists, including task being in a parent project
            task_project_cal_id = c.fetchone()
            if task_project_cal_id:
                task_project_cal_id = task_project_cal_id[0]

            c.execute("SELECT calendar_id FROM gcal_ids WHERE todoist_project_id = ?", (parent_id,))

            # if calendar for parent project exists
            task_parent_cal_id = c.fetchone()
            if task_parent_cal_id:
                task_parent_cal_id = task_parent_cal_id[0]

            # if task_project_cal_id means it's in standalone_ids
            if task_project_cal_id and task_parent_cal_id:
                cal_id = task_project_cal_id
            else:
                cal_id = task_parent_cal_id
        conn.close()

        return cal_id

    def find_label_id(self, label_name):
        """ Returns Todoist label id. """
        label_id = None
        for label in Todoist.api.labels.all():
            if label['name'] == label_name:
                label_id = label['id']
        return label_id

    def find_task_calId(self, project_id, parent_project_id):
        """
            if 'project_id' match is found before 'parent_project_id', then
            the task belongs to a standalone project, otherwise it belongs to its
            'parent_project_id' (order matters).
        """

        conn = sqlite3.connect('db/data.db')

        calendar_id = None
        with conn:
            c = conn.cursor()

            c.execute("SELECT calendar_id FROM gcal_ids WHERE todoist_project_id = ?", \
                (project_id,))

            standalone_calendar_id = c.fetchone()

            if standalone_calendar_id:
                calendar_id = standalone_calendar_id[0]
            else:
                c.execute("SELECT calendar_id FROM gcal_ids WHERE todoist_project_id = ?", \
                (parent_project_id,))

                calendar_id = c.fetchone()

                if calendar_id:
                    calendar_id = calendar_id[0]

        conn.close()
        return calendar_id

    ########### Assistive functions ###########
    def is_overdue(self, task_id):
        conn = sqlite3.connect('db/data.db')

        row_data = None
        with conn:
            c = conn.cursor()

            c.execute('''SELECT overdue integer FROM todoist WHERE task_id = ?''', (task_id,))

            row_data = c.fetchone()

        return True if row_data[0] else False

    def is_completed(self, task_id):
        op_code = False

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute("SELECT task_id FROM todoist_completed WHERE task_id = ?",( task_id,))

            # if task is found in 'todoist_completed'
            if c.fetchone():
                op_code = True
        return op_code

    def is_post_response_valid(self, sync_response):
        sync_schema_valid = True
        sync_err_schema_valid = True
        try:
            validate(sync_response, self.todoist_schema['sync'])
        except exceptions.ValidationError as err:
            sync_schema_valid = False
            log.debug(err)

            try:
                validate(sync_response, self.todoist_schema['http_error'])
            except exceptions.ValidationError as err:
                sync_err_schema_valid = False

        return (sync_schema_valid, sync_err_schema_valid)

    ########### Utility functions ###########
    def has_due_date_utc(self, todoist_item):
        """ Utility function to be used with filter for lists. """
        return True if todoist_item['due_date_utc'] else False

    def date_parser(self, date_str, frmt='%a %d %b %Y %H:%M:%S +0000'):
        """ Utility function to parse and convert a given date to the appropriate format. """
        converted_date_str = ''
        if type(date_str) is str:
            try:
                datetime_obj = dateutil.parser.parse(date_str)
                converted_date_str = datetime.strftime(datetime_obj, frmt)
            except Exception as err:
                log.exception(err)

        return converted_date_str

    def str_to_date_obj(self, date_str, frmt='%a %d %b %Y %H:%M:%S +0000'):
        """ Utility function to return str date to date object. """
        return datetime.strptime(date_str, frmt).date()

    def parse_google_date(self, google_date):
        """ Takes in a Todoist task's due date (UTC), and converts it to a normal date. """
        return datetime.strptime(google_date, '%Y-%m-%d')

    def __todoist_utc_to_date__(self, date_utc_str):
        """ Converts date from UTC to Todoist's timezone and returns a date obj. """
        if type(date_utc_str) is str:
            todoist_tz = pytz.timezone(self.sync.timezone())
            date_obj = None
            try:
                # tries to recover from date that may be in the wrong type, using a parser
                date_utc_str = self.date_parser(date_utc_str)
                date_obj = datetime.strptime(date_utc_str, "%a %d %b %Y %H:%M:%S +0000") \
                    .replace(tzinfo=pytz.UTC).astimezone(tz=todoist_tz).date()
            except Exception as err:
                log.exception(err)
            return date_obj

    def __date_to_google_format__(self, date_obj):
        return date_obj.isoformat()

    def __parent_project_id__(self, project_id):
        """ Unwinds projects until the parent project of the task is found. """
        parent_project_id = None
        project = Todoist.api.projects.get_by_id(project_id)

        while (project != None and project['indent'] != 1):
            project = Todoist.api.projects.get_by_id(project['parent_id'])
        if project:
            parent_project_id = project['id']

        return parent_project_id
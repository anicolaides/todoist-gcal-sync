"""
Performs common opertations on Todoist (Todoist <-- Gcal).

Dependencies: jsonschema, todoist-python, pytz, python-dateutil
"""

import todoist # todoist-python module
import os
import gcal
import sqlite3
from datetime import datetime, timedelta
import pytz
from urllib.parse import urlparse
import json
from jsonschema import exceptions
from jsonschema import validate
import time
import dateutil.parser
import todoist_auth
import logging
import sql_ops
import load_cfg

log = logging.getLogger(__name__)
__author__  = "Alexandros Nicolaides"
__status__  = "testing"

api = todoist.TodoistAPI(todoist_auth.todoist_api_token)
changed_location_of_event = None

initial_sync = api.sync() # needed to initialize 3 vars below
premium_user = api.user.state['user']['is_premium']
inbox_project_id = api.user.state['user']['inbox_project']

def data_init():
    """
        Data initialization of Todoist (db/data.db).
    """
    write_sync_db(api.sync())

    projects_to_gcal()

    if premium_user:
        init_completed_tasks()

    for project in api.projects.all():
        if not project['is_archived'] and not project['is_deleted'] and project['id'] != inbox_project_id:
            project_data = [project['name'], project['parent_id'], project['id'], project['indent']]
            sql_ops.insert_many("projects", project_data)

    for item in api.items.all(has_due_date_utc):
        # Todoist task --> Gcal event
        new_task_added(item)

    log.debug("Pausing operation for 10s, due to utilization of massive amount of requests.")
    time.sleep(10)

def projects_to_gcal():
    """
        Creates a calendar for each Todoist project, while taking into consideration
        'excluded_ids' and 'standalone_ids' table.
    """

    # create a calendar for each parent project, excluding project 'Inbox'
    for project in api.projects.all():
        standalone_project = False

        # if project is excluded
        if sql_ops.select_from_where("project_id", "excluded_ids", "project_id", \
                project['id']):
            log.info('The project \'' + api.projects.get_by_id(
            project['id'])['name'] + '\' is beeing excluded.')
        else:
            # search for project in "standalone_ids"
            if sql_ops.select_from_where("project_id", "standalone_ids", \
                "project_id", project['id']):
                standalone_project = True

            # for a standalone project, the project cannot be excluded or archived
            # create calendar for parent or standalone projects
            if not project['is_archived'] and (project['indent'] == 1 \
                and project['name'] != 'Inbox') or (project['indent'] != 1 \
                and project['name'] != 'Inbox' and standalone_project):
                gcal.create_calendar(project['name'], project['id'], timezone())

def exclude_projects():
    """
        Excludes projects from being synched.
    """

    excluded_projects = []
    for project_name in load_cfg.USER_PREFS['projects.excluded']:
        for todoist_project in api.projects.all():
            if project_name == todoist_project['name']:
                excluded_projects.append(todoist_project)

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
        if sql_ops.select_from_where("project_id", "standalone_ids", "project_id", \
                project_id):
            log.info('Project \'' + api.projects.get_by_id(project_id) \
                ['name'] + '\' is a standalone project, thus cannot be excluded.')
        else:
            # if not a standalone project, process further
            parent_id = __parent_project_id__(project_id)

            # if parent project is already excluded
            if sql_ops.select_from_where("project_id", "excluded_ids", "project_id", \
                    project_id):
                log.info('The parent project of the project to be excluded is already \
                    excluded.')
            else:
                # sub-projects of project to be excluded have already been excluded
                if sql_ops.select_from_where("parent_project_id", "excluded_ids", "parent_project_id", \
                    project_id):

                    # remove sub-projects of parent project
                    if sql_ops.delete_from_where("excluded_ids", "parent_project_id", project_id):
                        """
                            1. Delete calendar from gcal service.
                            2. Remove all the tasks with the project_id of calendar from db.
                            3. Insert project to 'excluded_ids'.
                        """
                        calendar_id = sql_ops.select_from_where("calendar_id", "gcal_ids", \
                            "todoist_project_id", project_id)

                        if gcal.delete_calendar(calendar_id) \
                            and sql_ops.delete_from_where("todoist", "parent_project_id", project_id):

                            sql_ops.delete_from_where("gcal_ids", "todoist_project_id", project_id)

                            if sql_ops.insert("excluded_ids", api.projects.get_by_id(project_id)['name'], project_id, parent_id):
                                log.info('The project with name \'' \
                                + api.projects.get_by_id(project_id)['name'] + \
                                '\' has been added to the \'excluded_ids\' table.')
                else:
                    if sql_ops.insert("excluded_ids", api.projects.get_by_id(project_id)['name'], project_id, parent_id):
                        log.info('The project with name \'' + api.projects.get_by_id(
                            project_id)['name'] + '\' has been added to the \'excluded_ids\' table.')

def standalone_projects():
    """
        Makes projects standalone.
    """
    standalone_projects = []
    for project_name in load_cfg.USER_PREFS['projects.standalone']:
        for project in api.projects.all():
            if project_name == project['name']:
                standalone_projects.append(project)

    for project in standalone_projects:
        if sql_ops.select_from_where("project_id", "excluded_ids", "project_id", project['id']):
            log.info('The project \'' + project['name'] + '\' is being excluded, \
                thus cannot become a standalone project.')
        else:
            # if not excluded
            parent_project_id = __parent_project_id__(project['id'])
            parent_proj_excluded = True

            if not load_cfg.USER_PREFS['projects.excluded']:
                parent_proj_excluded = False
            else:
                if not sql_ops.select_from_where("project_id", "excluded_ids", "project_id", parent_project_id):
                    parent_proj_excluded = False

            if not parent_proj_excluded and project['indent'] != 1:
                sql_ops.insert("standalone_ids", project['name'], project['id'])
            else:
                log.info('The parent project of ' + project['name'] + ' is already marked \
                    as a standalone project.')

def sync_todoist(initial_sync=None):
    # indicates the event was just moved
    changed_location_of_event = None

    write_to_db = True

    # retrieve last api.sync() from database
    prev_sync_resources = read_json_db()
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
        new_api_sync = api.sync()
    else:
        new_api_sync = initial_sync

    # case where Todoist sync is an empty string
    while new_api_sync == '':
        new_api_sync = api.sync()

    # Pauses until a valid Todoist API sync response is retrieved
    while not is_post_response_valid(new_api_sync)[0] or not is_post_response_valid(new_api_sync)[1]:
        if not is_post_response_valid(new_api_sync)[1]:
            if new_api_sync['error_tag'] == 'LIMITS_REACHED':
                log.critical('LIMITS_REACHED from Todoist; pausing operation for 8s...')
                time.sleep(8)
        new_api_sync = api.sync()

    changes = []
    note_changes = []
    project_changes = []
    if new_api_sync:
        new_api_sync_token = new_api_sync['sync_token']

        # was there a change between this and last api.sync() ?
        if prev_sync_token != new_api_sync_token:
            changes = new_api_sync['items']
            note_changes = new_api_sync['notes']
            project_changes = new_api_sync['projects']

    # for project changed, perform the following operations
    for k in range(0, len(project_changes)):
        project = project_changes[k]
        calendar_id = None
        calendar_name = None
        project_found = False

        calendar_data = sql_ops.select_from_where("calendar_id, calendar_name", "gcal_ids", "todoist_project_id", project['id'])

        if calendar_data is not None:
            calendar_id = calendar_data[0]
            calendar_name = calendar_data[1]
            project_found = True

        # new project
        if not project_found:
            if project['parent_id'] is None \
                and not project['is_archived'] and not project['is_deleted']:

                project_data = sql_ops.select_from_where("project_name, project_indent", "projects", "project_id", project['id'])
                if not project_data:
                    if gcal.create_calendar(project['name'], project['id'], timezone()):
                        row_data = [project['name'], project['parent_id'], project['id'], project['indent']]
                        sql_ops.insert_many("projects", row_data)
        else:
            project_data = sql_ops.select_from_where("project_name, project_indent", "projects", "project_id", project['id'])
            if project_data:
                project_name = project_data[0]
                prev_project_indent = project_data[1]
                project_parent_id = __parent_project_id__(project['id'])

                """
                # sub project becomes parent project
                if prev_project_indent != 1 and project['indent'] == 1 and not is_excluded(project['id']):

                    # remove tasks from calendar of prev parent project
                    tasks = sql_ops.select_from_where("event_id, task_id", "todoist", "project_id", project['id'], fetch_all=True)
                    for task in tasks:
                        event_id = task[0]
                        task_id = task[1]
                        calendar_id = find_cal_id(project['id'], find_cal_id(project['id'], project_parent_id))

                        # delete event from existing calendar
                        gcal.delete_event(calendar_id, event_id)

                    # remove tasks from "todoist" table
                    if sql_ops.delete_from_where("todoist", "project_id", project['id']):
                        log.debug("All events have been deleted from previous parent project calendar, to be moved to the new calendar.")

                    # create calendar as parent project
                    gcal.create_calendar(project['name'], project['id'], timezone())

                    # init tasks of particular project
                    for item in api.items.all(has_due_date_utc):
                        if item['project_id'] == project['id']:
                            # Todoist task --> Gcal event
                            new_task_added(item)

                    # update "projects" table to reflect new indentation level
                    sql_ops.update_set_where("projects", "project_indent = ?", "project_id = ?", project['indent'], project['id'])
                """

            if project['is_deleted'] or project['is_archived']:
                if gcal.delete_calendar(calendar_id):
                    log.info(project['name'] + " has been deleted successfully.")
                    sql_ops.delete_from_where("gcal_ids", "calendar_id", calendar_id)

                    # parent project
                    if project['parent_id'] is None:
                        if sql_ops.delete_from_where("todoist", "parent_project_id", project['id']):
                            log.info("Parent project's task clean up has been performed.")
                    else:
                        # sub project
                        if sql_ops.delete_from_where("todoist", "project_id", project['id']):
                            log.info("Project's task clean up has been performed.")
                    sql_ops.delete_from_where("projects", "project_id", project['id'])
            else:
                # Todoist --> Gcal (Project name sync)
                # Retrieve calendar name from db
                prev_project_name = (calendar_name.split('Project:')[1]).strip()
                if prev_project_name != project['name']:
                    # update calendar name
                    new_cal_name = 'Project: ' + project['name']
                    if gcal.update_cal_name(calendar_id, new_cal_name):
                        # update name in "gcal_ids" table
                        if sql_ops.update_set_where("gcal_ids", "calendar_name = ?", "calendar_id = ?", new_cal_name, calendar_id):
                            log.info("Calendar name has been synched with Gcal.")

                # parent project becomes sub project
                if project['id'] is not None and project['indent'] != 1:
                    # remove calendar from gcal
                    if gcal.delete_calendar(calendar_id):
                        log.info(str(project['name']) + " parent project has been deleted to become a sub project.")
                        # remove calendar from "gcal_ids" table
                        sql_ops.delete_from_where("gcal_ids", "calendar_id", calendar_id)

                        # remove tasks from "todoist" table
                        sql_ops.delete_from_where("todoist", "project_id", project['id'])

                        # init tasks of particular project
                        for item in api.items.all(has_due_date_utc):
                            if item['project_id'] == project['id']:
                                # Todoist task --> Gcal event
                                new_task_added(item)

                        sql_ops.update_set_where("projects", "parent_project_id = ?, project_indent = ?", "project_id = ?", project['parent_id'], project['indent'], project['id'])

    # if anything changed since last sync, then
    # for each changed item, perform the following operations
    for i in range(0, len(changes)):
        task_id = changes[i]['id']

        task_data = sql_ops.select_from_where("project_id, parent_project_id, due_date, event_id", "todoist", "task_id", task_id)

        if task_data:
            event_id = task_data[3]

            calendar_id = find_task_calId(task_data[0], task_data[1])

            if changes[i]['due_date_utc']:
                if calendar_id and task_data:

                    recurring_task_completed = False
                    if 'every' in changes[i]['date_string'].lower() and premium_user:
                        try:
                            # give some time for Todoist's servers to update activity log
                            time.sleep(2)

                            last_activity = api.activity.get()

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
                            if deletion(calendar_id, event_id, task_id):
                                log.info('Task with id: ' +  task_id + ' has been successfully deleted.')
                        except Exception as err:
                            write_to_db = False
                            log.exception(err)
                    elif recurring_task_completed and premium_user:
                        data_recurring = sql_ops.select_from_where("project_id, parent_project_id, due_date, event_id", "todoist", "task_id", task_id)
                        recurring_task_due_date = None
                        if data_recurring:
                            recurring_task_due_date = data_recurring[2]

                        if recurring_task_due_date != changes[i]['due_date_utc']:
                            if recurring_task_completed:
                                try:
                                    if checked(calendar_id, event_id, task_id, recurring_task_due_date):
                                        log.debug(str(task_id) + ': recurring task was checked.')
                                except Exception as err:
                                    write_to_db = False
                                    log.exception(str(err) + 'Could not mark the task with id: ' \
                                        + str(task_id) + ' as completed rec.')

                                if new_task_added(changes[i]):
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
                                date_google(calendar_id, changes[i]['due_date_utc'], \
                                    task_id, changes[i]['content'], event_id)
                            except Exception as err:
                                write_to_db = False
                                log.error(str(err) + 'Could not update date of event in Gcal...')

                        # Task name --> Event name (sync)
                        try:
                            task_name(calendar_id, event_id, task_id)
                        except Exception as err:
                            write_to_db = False
                            log.error(err)

                        # Task checked --> Gcal (sync)
                        # needs to be called after task name sync,
                        # for task with due date in the future to have a tick and be moved to today
                        if changes[i]['checked']:
                            try:
                                checked(calendar_id, event_id, task_id)
                            except Exception as err:
                                write_to_db = False
                                log.error(str(err) + ' Could not mark the task with id: ' \
                                    + str(task_id) + ' as completed from task checked.')

                        # Task location --> Gcal (sync)
                        if task_id and changes[i]['project_id'] == api.state['user']['inbox_project']:
                            # task moved back to Inbox --> remove from Gcal
                            try:
                                if deletion(calendar_id, event_id, task_id ):
                                    log.info('Task with id: ' + str(task_id) + ' has been deleted successfully.')
                            except Exception as err:
                                pass
                        elif task_id and task_location(calendar_id, event_id, task_id, changes[i]['project_id']):
                            log.info(str(task_id) + ' has been moved to a different project.')

            else:
                # remove event from Gcal
                try:
                    if deletion(calendar_id, event_id, task_id ):
                        log.info('Task with id: ' + str(task_id) + ' has been deleted successfully.')
                except Exception as err:
                    write_to_db = False
                    log.error(str(err))
        elif not changes[i]['checked']:
            """ Undo operation detected. """
            if is_completed(task_id):
                undo(task_id)

            # task with due date has not been deleted
            elif changes[i]['due_date_utc']:
                try:
                    new_task_added(changes[i])
                except Exception as err:
                    write_to_db = False
                    log.exception('task id: ' + str(task_id) \
                        + ' could not be added to Google Calendar.')

    # for each note changed, perform the following operations
    for j in range(0, len(note_changes)):

        # Task note added --> gcal desc (sync)
        if note_changes[j]['item_id']:
            update_desc_location(note_changes[j]['item_id'])

    if write_to_db:
        write_sync_db(new_api_sync)

def write_sync_db( json_str=None):
    if json_str:
        # truncate table each time, before inserting data
        sql_ops.truncate_table("todoist_sync")

        # combine row of data
        todoist_json_info = [json.dumps(json_str), json_str['sync_token'], ]

        sql_ops.insert_many("todoist_sync", todoist_json_info)
    else:
        log.warning('Nothing was provided to be synched.')

def read_json_db():
    last_sync_json = None

    # fetches and places each one in a list
    json_data = sql_ops.select_from_where("api_dot_sync, sync_token", "todoist_sync")

    if json_data:
        last_sync = json_data[0]

        last_sync_json = json.loads(last_sync)
    else:
        log.debug('Could not retrieve the data from todoist_sync database.')

    return last_sync_json

def delete_task(task_id):
    op_code = True

    if task_id:
        item = api.items.get_by_id(task_id)
        if item is not None:
            item.delete()
            api.commit()

            # if task is found in the 'todoist' table
            if not sql_ops.delete_from_where("todoist", "task_id", task_id):
                op_code = False

    return op_code

def update_task_due_date( cal_id, event_id, task_id, new_event_date):
    todoist_tz = pytz.timezone(timezone())

    due_date = sql_ops.select_from_where("due_date", "todoist", "task_id", task_id)
    if due_date:
        # turn google date to todoist utc date
        due_date = due_date[0]
        new_due_date = parse_google_date(new_event_date)
        new_due_date = new_due_date.replace(hour=21, minute=59, second=59)
        new_due_date = new_due_date.isoformat()

        try:
            item = api.items.get_by_id(task_id)
            item.update(due_date_utc=str(new_due_date))
            api.commit()
        except Exception as err:
            log.error(err)

        event_name = compute_event_name(item)
        try:
            gcal.update_event_date(cal_id, event_id, None, event_name , None)
        except Exception as err:
            log.error(err)

        try:
            task_due_date = __todoist_utc_to_date__(item['due_date_utc'])
        except Exception as err:
            log.exception(err)

        difference = (task_due_date - datetime.now(todoist_tz).date()).days

        # if task is not overdue and task was overdue previously
        if difference >= 0 and not is_overdue(task_id):
            gcal.update_event_color(cal_id,event_id,None)
        else:
            gcal.update_event_color(cal_id,event_id,11)

        sql_ops.update_set_where("todoist", "due_date = ?", "task_id = ?", item['due_date_utc'], task_id)

def init_completed_tasks():
    completed_task = api.completed.get_all(limit=200)['items']

    for k in range(0, len(completed_task)):
        task_id = None
        item = None
        valid_completed_task = True
        valid_item = True

        try:
            validate(completed_task[k], load_cfg.TODOIST_SCHEMA['completed_item'])
        except:
            valid_completed_task = False

        if valid_completed_task:
            # Todoist task --> Gcal event adds them to the day they were completed
            task_id = completed_task[k]['task_id']

            item = api.items.get(task_id)
            if item is not None:
                try:
                    item = item['item']
                    validate(item, load_cfg.TODOIST_SCHEMA['items'])
                except:
                    valid_item = False

                try:
                    if valid_item and item['due_date_utc'] and completed_task[k]['completed_date'] \
                        and new_task_added(item, completed_task[k]['completed_date']):

                        # grab the data from the db to supply them to the sync.checked func
                        # attempt to retrieve the data for the task using the "todoist" table
                        task_data = sql_ops.select_from_where("project_id, parent_project_id, event_id", "todoist", "task_id", task_id)

                        if task_data:
                            event_id = task_data[2]

                            calendar_id = find_task_calId(task_data[0], task_data[1])

                            checked(calendar_id,event_id,task_id, True)
                except Exception as err:
                    log.exception(err)

########### Retrieval functions ###########

########### gcal-sync-handlers  ###########
def get_task(task_id):
    """ Returns todoist task item, given a task id. """
    return api.items.get_by_id(task_id)

########### gcal-sync-handlers  ###########

def get_task_id(event_id):
    task_id = sql_ops.select_from_where("task_id", "todoist", "event_id", event_id)

    if task_id:
        task_id = task_id[0]

    return task_id

def find_cal_id(project_id, parent_id):
    cal_id = None
    task_project_cal_id = None
    task_parent_cal_id = None

    # check if standalone project of calendar exists, including task being in a parent project
    task_project_cal_id = sql_ops.select_from_where("calendar_id", "gcal_ids", "todoist_project_id", project_id)
    if task_project_cal_id:
        task_project_cal_id = task_project_cal_id[0]

    # if calendar for parent project exists
    task_parent_cal_id = sql_ops.select_from_where("calendar_id", "gcal_ids", "todoist_project_id", parent_id)
    if task_parent_cal_id:
        task_parent_cal_id = task_parent_cal_id[0]

    # if task_project_cal_id means it's in standalone_ids
    if task_project_cal_id and task_parent_cal_id:
        cal_id = task_project_cal_id
    else:
        cal_id = task_parent_cal_id

    return cal_id

def find_label_id(label_name):
    """ Returns Todoist label id. """
    label_id = None
    for label in api.labels.all():
        if label['name'] == label_name:
            label_id = label['id']
    return label_id

def find_task_calId(project_id, parent_project_id):
    """
        if 'project_id' match is found before 'parent_project_id', then
        the task belongs to a standalone project, otherwise it belongs to its
        'parent_project_id' (order matters).
    """
    calendar_id = None

    standalone_calendar_id = sql_ops.select_from_where("calendar_id", "gcal_ids", "todoist_project_id", project_id)

    if standalone_calendar_id:
        calendar_id = standalone_calendar_id[0]
    else:
        calendar_id = sql_ops.select_from_where("calendar_id", "gcal_ids", "todoist_project_id", parent_project_id)

        if calendar_id:
            calendar_id = calendar_id[0]

    return calendar_id

########### Assistive functions ###########
def is_overdue(task_id):
    row_data = sql_ops.select_from_where("overdue", "todoist", "task_id", task_id)

    return True if row_data[0] else False

def is_completed(task_id):
    return True if sql_ops.select_from_where("task_id", "todoist_completed", "task_id", task_id) else False

def is_post_response_valid(sync_response):
    sync_schema_valid = True
    sync_err_schema_valid = True
    try:
        validate(sync_response, load_cfg.TODOIST_SCHEMA['sync'])
    except exceptions.ValidationError as err:
        sync_schema_valid = False
        log.debug(err)

        try:
            validate(sync_response, load_cfg.TODOIST_SCHEMA['http_error'])
        except exceptions.ValidationError as err:
            sync_err_schema_valid = False

    return (sync_schema_valid, sync_err_schema_valid)

def is_excluded(project_id):
    """ Returns true if project is being excluded. """
    return True if sql_ops.select_from_where("project_name", "excluded_ids", "project_id", project_id) else False

# TODO: not used anywhere yet
def is_standalone(project_id):
    """ Returns true if project uses a standalone calendar. """
    return True if sql_ops.select_from_where("project_name", "standalone_ids", "project_id", project_id) else False
########### Utility functions ###########
def has_due_date_utc(todoist_item):
    """ Utility function to be used with filter for lists. """
    return True if todoist_item['due_date_utc'] else False

def date_parser(date_str, frmt='%a %d %b %Y %H:%M:%S +0000'):
    """ Utility function to parse and convert a given date to the appropriate format. """
    converted_date_str = ''
    if type(date_str) is str:
        try:
            datetime_obj = dateutil.parser.parse(date_str)
            converted_date_str = datetime.strftime(datetime_obj, frmt)
        except Exception as err:
            log.exception(err)

    return converted_date_str

def str_to_date_obj(date_str, frmt='%a %d %b %Y %H:%M:%S +0000'):
    """ Utility function to return str date to date object. """
    return datetime.strptime(date_str, frmt).date()

def parse_google_date(google_date):
    """ Takes in a Todoist task's due date (UTC), and converts it to a normal date. """
    return datetime.strptime(google_date, '%Y-%m-%d')

def __todoist_utc_to_date__( date_utc_str):
    """ Converts date from UTC to Todoist's timezone and returns a date obj. """
    if type(date_utc_str) is str:
        todoist_tz = pytz.timezone(timezone())
        date_obj = None
        try:
            # tries to recover from date that may be in the wrong type, using a parser
            date_utc_str = date_parser(date_utc_str)
            date_obj = datetime.strptime(date_utc_str, "%a %d %b %Y %H:%M:%S +0000") \
                .replace(tzinfo=pytz.UTC).astimezone(tz=todoist_tz).date()
        except Exception as err:
            log.exception(err)
        return date_obj

def __date_to_google_format__(date_obj):
    return date_obj.isoformat()

def __parent_project_id__( project_id):
    """ Unwinds projects until the parent project of the task is found. """
    parent_project_id = None
    project = api.projects.get_by_id(project_id)

    while (project != None and project['indent'] != 1):
        project = api.projects.get_by_id(project['parent_id'])
    if project:
        parent_project_id = project['id']

    return parent_project_id

########### Sync handlers ###########
def timezone():
    """
        Synchronizes Todoist timezone.
    """
    return api.state['user']['tz_info']['timezone']

def task_name( calendar_id, event_id, task_id):
    op_code = False

    item = api.items.get_by_id(task_id)

    if item is not None and item['content']:
        event_name = compute_event_name(item)

        if gcal.update_event_date(calendar_id, event_id, None, event_name, None):
            op_code = True

    return op_code

def compute_event_name( todoist_item, completed_task=None):
    parent_project = api.projects.get_by_id(
        __parent_project_id__(todoist_item['project_id']))
    project = api.projects.get_by_id(todoist_item['project_id'])
    event_name = ''
    icons_cfg = load_cfg.ICONS

    # if reccuring, append a unicode icon showing reccurence to the front of the event name
    # case insensitive comparisson of the keyword 'every'
    if load_cfg.USER_PREFS['appearance.displayReccuringIcon'] \
        and 'every' in todoist_item['date_string'].lower():
        if load_cfg.USER_PREFS['appearance.displayReccuringIconCompleted'] \
        and completed_task or not completed_task:
            event_name += icons_cfg['icons.basic']['recurring'] + ' '

    url_found = False
    label_icon = False
    # appends icons based on task labels
    task_labels = todoist_item['labels']
    if task_labels:
        for label_id in task_labels:
            for icon_group in icons_cfg['icons.labels']:
                for label_name in icons_cfg['icons.labels'][icon_group]:
                    if label_id == find_label_id(label_name):
                        event_name += icons_cfg['icons.labels'][icon_group][label_name] + ' '
                        label_icon = True

    if project and parent_project:
        parsed_icon = False
        # appends icons based on context of task name, using a parser
        for category in icons_cfg['icons.parser']:
            if category == "general":
                for keyword in icons_cfg['icons.parser'][category]:
                    if keyword in todoist_item['content'].lower().split():
                        event_name += icons_cfg['icons.parser'][category][keyword] + ' '
                        parsed_icon = True
            else:
                for i in range(0, len(icons_cfg['icons.parser'][category])):
                    keys = icons_cfg['icons.parser'][category][i]['keywords']
                    if any(keyword in todoist_item['content'].lower().split() for keyword in keys):
                        if category == 'or_and_project':
                            if icons_cfg['icons.parser'][category][i]['project_name'] == project['name'].lower():
                                event_name += icons_cfg['icons.parser'][category][i]['icon'] + ' '
                                parsed_icon = True
                        else:
                            event_name += icons_cfg['icons.parser'][category][i]['icon'] + ' '
                            parsed_icon = True

        # if the parser above has not added any icon
        if not parsed_icon and not label_icon:
            # by project name
            for label in icons_cfg['icons.projects']:
                if label == project['name'].lower():
                    event_name += icons_cfg['icons.projects'][label] + ' '

            # by parent project name
            for label in icons_cfg['icons.parentProjects']:
                if label == parent_project['name'].lower():
                    event_name += icons_cfg['icons.parentProjects'][label] + ' '

    # detect url in todoist task name
    if '(' and ')' in todoist_item['content']:
        url = urlparse(todoist_item['content'])
        if url.scheme:
            url_found = True
            # use article or website name as event name for task
            event_name += icons_cfg['icons.basic']['url'] + ' ' + todoist_item['content'].split('(')[1].strip(')')

    if not url_found:
        event_name += todoist_item['content']

    temp_name = event_name
    priority_icons = load_cfg.ICONS['icons.prioritySet1']

    if todoist_item['priority'] == 4:  # Red flag in Todoist
        event_name = priority_icons[0].strip() + ' ' + temp_name
    elif todoist_item['priority'] == 3:  # Orange flag in Todoist
        event_name = priority_icons[1].strip() + ' ' + temp_name
    elif todoist_item['priority'] == 2:  # Yellow flag in Todoist
        event_name = priority_icons[2].strip() + ' ' + temp_name
    elif todoist_item['priority'] == 1:  # Grey/White flag in Todoist
        event_name = priority_icons[3].strip() + ' ' + temp_name

    if not completed_task:
        todoist_tz = pytz.timezone(timezone())
        item_due_date = __todoist_utc_to_date__(todoist_item['due_date_utc'])
        difference = (item_due_date - datetime.now(todoist_tz).date()).days

        if difference < 0:
            # overdue task
            event_name = icons_cfg['icons.basic']['overdue'] + ' ' + event_name

    return event_name

def event_desc( todoist_item):
    # URL detection in task name
    desc = ''
    url = urlparse(todoist_item['content'])
    if url.scheme:
        # grabs url of website
        desc += todoist_item['content'].split()[0]

    # Premium only
    # Set event description to task's comments, along with a delimeter
    if premium_user:
        try:
            task_notes = api.items.get(todoist_item['id'])
            if task_notes:
                task_notes = task_notes['notes']

                for note in range(0, len(task_notes)):
                    desc += task_notes[note]['content'] + '\n\n'
        except Exception as err:
            log.error(err)
    return desc

def overdue():
    log.info('Overdue function was run.')

    not_overdue_tasks = sql_ops.select_from_where( \
        "due_date, event_id, task_id, project_id, parent_project_id", "todoist", "overdue is NULL", None, True)
    if not_overdue_tasks:
        for task in range(0, len(not_overdue_tasks)):
            task_due_date = __todoist_utc_to_date__(not_overdue_tasks[task][0])

            todoist_tz = pytz.timezone(timezone())
            date_in_todoist_tz = datetime.now(todoist_tz).date()
            difference = (task_due_date - date_in_todoist_tz).days

            task_id = not_overdue_tasks[task][2]
            item = api.items.get_by_id(task_id)

            if difference < 0 and item is not None:
                overdue = True

                # update priority of task from p2 to p1
                if item['priority'] == 3: # p2 in Todoist client
                    item.update(priority=4) # p1 in Todoist client
                    api.commit()

                event_name = compute_event_name(item)

                calendar_id = find_task_calId(not_overdue_tasks[task][3], \
                    not_overdue_tasks[task][4])

                if calendar_id:
                    if gcal.update_event_summary(calendar_id, \
                        not_overdue_tasks[task][1], event_name) and \
                        gcal.update_event_color(calendar_id, \
                        not_overdue_tasks[task][1], 11):

                        # update 'todoist' table to reflect overdue status
                        if sql_ops.update_set_where("todoist", "overdue = ? ", "task_id = ?", overdue, task_id):
                            log.info('Task with id: ' + str(item['id']) + ' has become overdue.')
                        else:
                            log.warning('Could update event date on Gcal, but could not update \
                                Todoist table.')
                    else:
                        log.error('ERROR:  + overdue()')

                # keeps times_overdue up-to-date
                data = sql_ops.select_from_where("times_overdue", "todoist", "task_id", task_id)

                if data:
                    times_overdue = data[0]

                    if times_overdue is not None:
                        times_overdue += 1
                    else:
                        times_overdue = 1
                    sql_ops.update_set_where("todoist", "times_overdue = ?", "task_id = ?", times_overdue, task_id)

def date_google( calendar_id, new_due_date=None, item_id=None, item_content=None, event_id=None, extended_date=None):
    op_code = False
    overdue = None
    todoist_tz = pytz.timezone(timezone())

    if calendar_id and event_id and (new_due_date or extended_date):
        event_name = None
        colorId = None
        difference = None
        new_event_date = None
        extended_utc = None

        item = api.items.get_by_id(item_id)

        # convert new event date to Gcal format
        if new_due_date:
            new_event_date = __todoist_utc_to_date__(new_due_date)
            difference = (new_event_date - datetime.now(todoist_tz).date()).days
            new_event_date = __date_to_google_format__(new_event_date)

        # convert extended_utc date to Gcal format
        if extended_date:
            overdue_due_date = __todoist_utc_to_date__(item['due_date_utc'])
            difference = (overdue_due_date - datetime.now(todoist_tz).date()).days

            extended_utc = __todoist_utc_to_date__(str(extended_date))
            #extended_utc += timedelta(days=1)
            extended_utc = __date_to_google_format__(extended_utc)

        event_name = compute_event_name(item)

        if difference < 0:
            overdue = True
            event_name = load_cfg.ICONS['icons.basic']['overdue'] + ' ' + event_name
            colorId = 11
        elif difference >= 0 and is_overdue(item_id):
            # keep color to overdue
            colorId = 11

        if gcal.update_event_date(calendar_id, event_id, new_event_date, event_name,\
            colorId, extended_utc) and new_due_date:

            # update 'todoist' table with new due_date_utc
            if sql_ops.update_set_where("todoist", "due_date = ?, event_id = ?, overdue = ?", "task_id = ?", new_due_date, event_id, overdue ,item_id):
                op_code = True
            else:
                op_code = False
                log.warning('Could update event date on Gcal, but could not update Todoist table.')

    return op_code

def deletion( calendar_id, event_id, task_id=None):
    op_code = False

    if gcal.delete_event(calendar_id, event_id):
        if sql_ops.delete_from_where("todoist", "task_id", task_id):
            op_code = True
        else:
            log.debug('Could not delete task from database of todoist.')
    return op_code

def checked( cal_id, event_id, task_id, completed_task=None, old_due_date_utc=None):
    op_code = False

    if cal_id and event_id and task_id:
        todoist_item = api.items.get_by_id(task_id)

        if not completed_task:
            if not old_due_date_utc:
                task_due_date_utc = str_to_date_obj(todoist_item['due_date_utc'])
            else:
                task_due_date_utc = str_to_date_obj(old_due_date_utc)

            todoist_tz = pytz.timezone(timezone())
            todays_date_utc = datetime.now(todoist_tz).astimezone(pytz.utc).date()
            difference = (task_due_date_utc - todays_date_utc).days

            if difference > 0:
                datetime_todoist_frmt = datetime.now(pytz.UTC).strftime("%a %d %b %Y %H:%M:%S +0000")

                # move event to today's day using the gcal.date_google which will
                # also update the 'todoist' table with the new due date
                try:
                    date_google(cal_id, datetime_todoist_frmt, todoist_item['id'], \
                        todoist_item['content'], event_id)
                except Exception as err:
                    log.error(str(err) + '\nCould not update date of event in Gcal...')
            # if task was due yesterday and got completed today extend event length
            # to the next day
            elif difference < 0:
                todoist_item = api.items.get_by_id(task_id)
                extended_date_utc = None
                extended_date_utc = datetime.now(todoist_tz).astimezone(pytz.utc).replace(hour=21, minute=59, second=59)

                # extend duration of event before ticking it
                try:
                    date_google(cal_id, None, todoist_item['id'], \
                        todoist_item['content'], event_id,  extended_date_utc)
                except Exception as err:
                    log.error(str(err) + '\nCould not update date of event in Gcal...' )

                # restore event color from overdue color
                gcal.update_event_color(cal_id, event_id, None)

        event_name = '✓ ' + compute_event_name(todoist_item, True)
        try:
            if gcal.update_event_summary(cal_id, event_id, event_name):
                log.debug('Task ' + str(task_id) + ' has been completed.')
                op_code = True
            else:
                log.error('We could not update event name to reflect completion of task \
                    in ')
        except Exception as err:
            log.exception(err)

    # if could append tickmark to the front of Todoist
    if op_code:

        row_data = sql_ops.select_from_where('''project_id integer, parent_project_id integer, task_id integer,
            due_date text, event_id integer, overdue integer, times_overdue integer,
            times_resheduled_on_due_date''', "todoist", "task_id", task_id)

        if row_data:
            # to allow for undo functionality
            if sql_ops.insert_many("todoist_completed", row_data):
                sql_ops.delete_from_where("todoist", "task_id", task_id)

        # remove popup reminder from event, since the event is completed
        gcal.update_event_reminders(cal_id, event_id)

    return op_code

def new_task_added( item, completed_due_utc=None):
    task_added = False
    include_task = True
    if item is not None:
        if load_cfg.USER_PREFS['projects.excluded'] \
            and sql_ops.select_from_where("project_id", "excluded_ids", "project_id", item['project_id']):
                include_task = False

        # prevent duplicates
        # if not recurring, check tables "todoist" and "todoist_completed" for task_id
        if not 'every' in item['date_string'].lower():
            if sql_ops.select_from_where("due_date", "todoist_completed", "task_id", item['id']) \
                or sql_ops.select_from_where("due_date", "todoist", "task_id", item['id']):
                include_task = False
        else:
            # TODO: this may not work at all
            # recurring
            dates_from_completed = sql_ops.select_from_where("due_date", "todoist_completed", "task_id", item['id'], True)
            if dates_from_completed:
                date_utc_str = date_parser(item['due_date_utc'])
                due_date_utc = datetime.strptime(date_utc_str, "%a %d %b %Y %H:%M:%S +0000").date()

                for date in dates_from_completed:
                    date = date_parser(date[0])

                    # convert str dates to date objects for comparison
                    table_date = datetime.strptime(date, "%a %d %b %Y %H:%M:%S +0000").date()

                    if table_date == due_date_utc:
                        include_task = False
                        break

        parent_id = __parent_project_id__(item['project_id'])
        if include_task and parent_id and item['due_date_utc'] and item['project_id'] != inbox_project_id:
            due_date_utc = None
            colorId = None
            overdue = None
            completed_date_utc = None

            if not completed_due_utc:
                due_date_utc = __todoist_utc_to_date__(item['due_date_utc'])

                # set overdue task's color to bold red and append a unicode icon to the front
                task_due_date = __todoist_utc_to_date__(item['due_date_utc'])

                todoist_tz = pytz.timezone(timezone())
                difference = (task_due_date - datetime.now(todoist_tz).date()).days
                if difference < 0:
                    # if overdue and p2 --> slip to q1 in Todoist
                    todoist_item = api.items.get_by_id(item['id'])
                    todoist_item.update(priority=4)
                    api.commit()
                    colorId = 11
                    overdue = True
            else:
                completed_utc = datetime.strptime(completed_due_utc, "%a %d %b %Y %H:%M:%S +0000").date()
                task_due_date_utc = datetime.strptime(item['due_date_utc'], "%a %d %b %Y %H:%M:%S +0000").date()
                difference = abs((task_due_date_utc - completed_utc).days)

                # events to be extended_utc
                if completed_utc > task_due_date_utc and difference > 0 and difference < 3:
                    due_date_utc = __todoist_utc_to_date__(item['due_date_utc'])
                    completed_date_utc = __todoist_utc_to_date__(completed_due_utc)

                    # increment end date by one, for google calendar end date
                    completed_date_utc = completed_date_utc + timedelta(days=1)
                else:
                    # add completed tasks to the date they were completed
                    due_date_utc = __todoist_utc_to_date__(completed_due_utc)

            event_start_datetime = __date_to_google_format__(due_date_utc)
            if completed_date_utc:
                event_end_datetime = __date_to_google_format__(completed_date_utc)
            else:
                event_end_datetime = None

            event_location = task_path(item['id'])
            cal_id = find_cal_id(item['project_id'], parent_id)
            event_name = compute_event_name(item, completed_due_utc)
            desc = event_desc(item)

            # create all-day event for each task
            try:
                event_id = gcal.insert_event(cal_id, event_name, event_start_datetime, \
                event_end_datetime, event_location, desc, timezone(), colorId)

                item_due_date = None
                if not completed_due_utc:
                    item_due_date = item['due_date_utc']
                else:
                    item_due_date = completed_due_utc

                if event_id:
                    todoist_item_info = [item['project_id'], parent_id, item['id'], \
                        str(item_due_date), event_id, overdue, None, None ]

                    if sql_ops.insert_many("todoist", todoist_item_info):
                        task_added = True
            except Exception as err:
                log.exception(err)
    return task_added

def task_location( calendar_id, event_id, task_id, project_id):
    op_code = False

    parent_project_id = __parent_project_id__(project_id)

    # if project_id and parent_project_id did not change returns row of data, else
    # if task has been moved to another project or parent project, returns None
    data = sql_ops.select_from_where("project_id", "todoist", "task_id = ? AND project_id = ? AND parent_project_id = ?",
        None, False, False, task_id, project_id, parent_project_id)

    # if we have a new project_id, we may have a new parent_project_id as well
    # either the project_id or the parent_project_id or both are different
    if not data:
        event_location = task_path(task_id)

        cal_id = find_cal_id(project_id, parent_project_id)

        try:
            if gcal.update_event_location(calendar_id, event_id, event_location, cal_id):
                # calendar_id != destination calendar id
                if calendar_id != cal_id:
                    # assume the .move() function was called
                    changed_location_of_event = event_id
                op_code = True

                # update project_id and parent_project_id of db with the new data,
                # so we can perform the move again
                if sql_ops.update_set_where("todoist", "project_id = ?, parent_project_id = ?", "task_id = ?", \
                    parent_project_id, project_id , task_id):
                    op_code = True
                else:
                    log.error('\nCould update event date on Gcal, but could not update Todoist table.')
        except Exception as err:
            log.exception(err)
    return op_code

def undo( task_id):
    # move task data back to "todoist" table
    if is_completed(task_id):
        data_row = sql_ops.select_from_where('''project_id integer, parent_project_id integer, task_id integer,
            due_date text, event_id integer, overdue integer, times_overdue integer,
            times_resheduled_on_due_date integer''', "todoist_completed", "task_id", None, None, task_id)

        if data_row and sql_ops.insert_many("todoist", data_row):
            sql_ops.delete_from_where("todoist_completed", "task_id", task_id)

            # retrieve calendar_id of the task
            calendar_id = sql_ops.select_from_where("calendar_id", "gcal_ids", "todoist_project_id = ? OR todoist_project_id = ?",
                None, False, False, data_row[0],data_row[1])

            if calendar_id:
                calendar_id = calendar_id[0]

            # sync date because if it was overdue and was stetched it won't go back to normal just like that
            try:
                item = api.items.get_by_id(task_id)
                if item is not None:
                    date_google(calendar_id, item['due_date_utc'], task_id, item['content'], data_row[4])
            except Exception as err:
                log.exception(str(err) + 'Could not update date of event in Gcal...')

            # call sync task name now that the data is back in the "todoist" table
            # task name --> event name (sync)
            # this has to be called after the code block above, so that icon priority is preserved
            try:
                task_name(calendar_id, data_row[4], task_id)
            except Exception as err:
                log.exception(err)

            try:
                # add the reminder popup back, since the event got unticked
                gcal.update_event_reminders(calendar_id, data_row[4], 300)
            except Exception as err:
                log.exception(str(err) + ' from updating event reminders in undo')

def task_path( task_id):
    """
        Compose event location for each event added to Gcal.
    """
    event_location = ''
    if premium_user:
        try:
            task_notes = api.items.get(task_id)
            if task_notes and task_notes['notes']:
                event_location = '✉ '
        except Exception as err:
            log.debug(err)

    item = api.items.get_by_id(task_id)

    if item is not None and task_id:
        parent_id = __parent_project_id__(item['project_id'])
        if parent_id is None:
            log.error("Todoist error: 'parent_id' of project " + str(item['project_id']) \
            + " is set to None.")

        # find the child project the task resides in
        project_of_item = api.projects.get_by_id(item['project_id'])

        if parent_id and project_of_item != None and project_of_item['indent'] != 1:
            event_location += api.projects.get_by_id(parent_id)['name'] \
                + ', ' + project_of_item['name']
        elif project_of_item != None and project_of_item['indent'] == 1:
            event_location += project_of_item['name']
        parent_of_task = api.items.get_by_id(item['id'])

        # append the name of the parent task to the location of the event of the sub-task
        if item['indent'] != 1 and item['parent_id'] != None:
            event_location += ', ' + parent_of_task['content']
    return event_location

def update_desc_location( task_id):
    """
        Updates event description and location, due to a change in task's notes.
    """

    new_event_location = task_path(task_id)
    item = api.items.get_by_id(task_id)
    new_desc = event_desc(item)

    parent_project_id = __parent_project_id__(item['project_id'])
    cal_id = find_cal_id(item['project_id'], parent_project_id)

    event_id = None

    # find event id
    task_data = sql_ops.select_from_where("project_id, parent_project_id, due_date, event_id", "todoist", "task_id", task_id)

    if task_data:
        event_id = task_data[3]

    if event_id:
        gcal.update_event_location(cal_id, event_id, new_event_location, cal_id)
        gcal.update_event_desc(cal_id, event_id, new_desc)

def module_init():
    # if db exists, skip first time initialization
    if os.path.exists(load_cfg.DB_PATH):
        # to prevent losing sync data when the daemon shuts down
        sync_todoist(initial_sync)
    else:
        sql_ops.init_db()

        if load_cfg.USER_PREFS['projects.standalone']:
            standalone_projects()
        if load_cfg.USER_PREFS['projects.excluded']:
            exclude_projects()
        data_init()
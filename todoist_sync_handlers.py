"""
File: todoist_sync_handlers.py
Purpose: Todoist sync handling operations.
Author: Alexandros Nicolaides
Dependencies: pytz
"""

from datetime import datetime, timedelta
from gcal import Gcal
import todo
import sqlite3
import pytz
from urllib.parse import urlparse
import logging
import load_cfg
import time

log = logging.getLogger(__name__)

class TodoistSync:
    def __init__(self, caller):
        self.__gcal = Gcal(caller)
        self.__todoist = caller

    def timezone(self):
        """
            Synchronizes Todoist timezone.
        """
        return self.__todoist.api.state['user']['tz_info']['timezone']

    def task_name(self, calendar_id, event_id, task_id):
        op_code = False

        item = self.__todoist.api.items.get_by_id(task_id)

        if item is not None and item['content']:
            event_name = self.event_name(item)

            if self.__gcal.update_event_date(calendar_id, event_id, None, event_name, None):
                op_code = True

        return op_code

    def event_name(self, todoist_item, completed_task=None):
        parent_project = self.__todoist.api.projects.get_by_id(
            self.__todoist.__parent_project_id__(todoist_item['project_id']))
        project = self.__todoist.api.projects.get_by_id(todoist_item['project_id'])
        event_name = ''
        icons_cfg = load_cfg.ICONS

        # if reccuring, append a unicode icon showing reccurence to the front of the event name
        # case insensitive comparisson of the keyword 'every'
        if self.__todoist.settings['appearance.displayReccuringIcon'] \
            and 'every' in todoist_item['date_string'].lower():
            if self.__todoist.settings['appearance.displayReccuringIconCompleted'] \
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
                        if label_id == self.__todoist.find_label_id(label_name):
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
            todoist_tz = pytz.timezone(self.timezone())
            item_due_date = self.__todoist.__todoist_utc_to_date__(todoist_item['due_date_utc'])
            difference = (item_due_date - datetime.now(todoist_tz).date()).days

            if difference < 0:
                # overdue task
                event_name = icons_cfg['icons.basic']['overdue'] + ' ' + event_name

        return event_name

    def event_desc(self, todoist_item):
        # URL detection in task name
        desc = ''
        url = urlparse(todoist_item['content'])
        if url.scheme:
            # grabs url of website
            desc += todoist_item['content'].split()[0]

        # Premium only
        # Set event description to task's comments, along with a delimeter
        if self.__todoist.premium_user:
            try:
                task_notes = self.__todoist.api.items.get(todoist_item['id'])
                if task_notes:
                    task_notes = task_notes['notes']

                    for note in range(0, len(task_notes)):
                        desc += task_notes[note]['content'] + '\n\n'
            except Exception as err:
                log.error(err)
        return desc

    def overdue(self):
        log.info('Overdue function was run.')
        table_exists = True
        conn = sqlite3.connect('db/data.db')

        c = conn.cursor()

        with conn:
            try:
                c.execute("SELECT due_date, event_id, task_id, project_id, parent_project_id FROM \
                    todoist WHERE overdue is NULL")
            except sqlite3.OperationalError as err:
                log.warning(err)
                table_exists = False

            if table_exists:
                not_overdue_tasks = c.fetchall()

                if not_overdue_tasks:
                    for task in range(0, len(not_overdue_tasks)):
                        task_due_date = self.__todoist.__todoist_utc_to_date__(
                            not_overdue_tasks[task][0])

                        todoist_tz = pytz.timezone(self.timezone())
                        date_in_todoist_tz = datetime.now(todoist_tz).date()
                        difference = (task_due_date - date_in_todoist_tz).days

                        task_id = not_overdue_tasks[task][2]
                        item = self.__todoist.api.items.get_by_id(task_id)

                        if difference < 0 and item is not None:
                            overdue = True

                            # update priority of task from p2 to p1
                            if item['priority'] == 3: # p2 in Todoist client
                                item.update(priority=4) # p1 in Todoist client
                                self.__todoist.api.commit()

                            event_name = self.event_name(item)

                            calendar_id = self.__todoist.find_task_calId(not_overdue_tasks[task][3], \
                                not_overdue_tasks[task][4])

                            if calendar_id:
                                if self.__gcal.update_event_summary(calendar_id, \
                                    not_overdue_tasks[task][1], event_name) and \
                                    self.__gcal.update_event_color(calendar_id, \
                                    not_overdue_tasks[task][1], 11):

                                    # update 'todoist' table to reflect overdue status
                                    try:
                                        c.execute("UPDATE todoist SET overdue = ? WHERE task_id = ?",
                                            (overdue, task_id ,))
                                        conn.commit()
                                        log.info('Task with id: ' + str(item['id']) + ' has become overdue.')
                                    except sqlite3.OperationalError as err:
                                        log.error(err)
                                        log.warning('Could update event date on Gcal, but could not update \
                                            Todoist table.')
                                else:
                                    log.error('ERROR:  + overdue()')

                            # keeps times_overdue up-to-date
                            c.execute("SELECT times_overdue FROM todoist WHERE task_id = ?", \
                                (task_id,))

                            data = c.fetchone()

                            if data:
                                times_overdue = data[0]

                                if times_overdue is not None:
                                    times_overdue += 1
                                else:
                                    times_overdue = 1

                                c.execute("UPDATE todoist SET times_overdue = ? WHERE task_id = ?", \
                                        (times_overdue, task_id,))
                                conn.commit()

        conn.close()

    def date_google(self, calendar_id, new_due_date=None, item_id=None, item_content=None, event_id=None, extended_date=None):
        op_code = False
        overdue = None
        todoist_tz = pytz.timezone(self.timezone())

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            if calendar_id and event_id and (new_due_date or extended_date):
                event_name = None
                colorId = None
                difference = None
                new_event_date = None
                extended_utc = None

                item = self.__todoist.api.items.get_by_id(item_id)

                # convert new event date to Gcal format
                if new_due_date:
                    new_event_date = self.__todoist.__todoist_utc_to_date__(new_due_date)
                    difference = (new_event_date - datetime.now(todoist_tz).date()).days
                    new_event_date = self.__todoist.__date_to_google_format__(new_event_date)

                # convert extended_utc date to Gcal format
                if extended_date:
                    overdue_due_date = self.__todoist.__todoist_utc_to_date__(item['due_date_utc'])
                    difference = (overdue_due_date - datetime.now(todoist_tz).date()).days

                    extended_utc = self.__todoist.__todoist_utc_to_date__(str(extended_date))
                    #extended_utc += timedelta(days=1)
                    extended_utc = self.__todoist.__date_to_google_format__(extended_utc)


                event_name = self.event_name(item)

                if difference < 0:
                    overdue = True
                    event_name = load_cfg.ICONS['icons.basic']['overdue'] + ' ' + event_name
                    colorId = 11
                elif difference >= 0 and self.__todoist.is_overdue(item_id):
                    # keep color to overdue
                    colorId = 11

                if self.__gcal.update_event_date(calendar_id, event_id, new_event_date, event_name,\
                    colorId, extended_utc) and new_due_date:

                    # update 'todoist' table with new due_date_utc
                    try:
                        c.execute("UPDATE todoist SET due_date = ?, event_id = ?, overdue = ? WHERE task_id = ?",
                            (new_due_date, event_id, overdue ,item_id,))
                        conn.commit()
                        op_code = True
                    except sqlite3.OperationalError as err:
                        log.error(err)
                        log.warning('Could update event date on Gcal, but could not update Todoist table.')
        conn.close()

        return op_code

    def deletion(self, calendar_id, event_id, task_id=None):
        op_code = False

        conn = sqlite3.connect('db/data.db')

        c = conn.cursor()

        with conn:
            if self.__gcal.delete_event(calendar_id, event_id):
                try:
                    c.execute("DELETE FROM todoist WHERE task_id = ?", (task_id,))
                    conn.commit()
                    op_code = True
                except sqlite3.OperationalError as err:
                    log.exception('Could not delete task from database of todoist.' + str(err))

        conn.close()
        return op_code

    def checked(self, cal_id, event_id, task_id, completed_task=None, old_due_date_utc=None):
        op_code = False

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            if cal_id and event_id and task_id:
                todoist_item = self.__todoist.api.items.get_by_id(task_id)

                if not completed_task:
                    if not old_due_date_utc:
                        task_due_date_utc = self.__todoist.str_to_date_obj(todoist_item['due_date_utc'])
                    else:
                        task_due_date_utc = self.__todoist.str_to_date_obj(old_due_date_utc)

                    todoist_tz = pytz.timezone(self.timezone())
                    todays_date_utc = datetime.now(todoist_tz).astimezone(pytz.utc).date()
                    difference = (task_due_date_utc - todays_date_utc).days

                    if difference > 0:
                        datetime_todoist_frmt = datetime.now(pytz.UTC).strftime("%a %d %b %Y %H:%M:%S +0000")

                        # move event to today's day using the self.__gcal.date_google which will
                        # also update the 'todoist' table with the new due date
                        try:
                            self.date_google(cal_id, datetime_todoist_frmt, todoist_item['id'], \
                                todoist_item['content'], event_id)
                        except Exception as err:
                            log.error(str(err) + '\nCould not update date of event in Gcal...')
                    # if task was due yesterday and got completed today extend event length
                    # to the next day
                    elif difference < 0:
                        todoist_item = self.__todoist.api.items.get_by_id(task_id)
                        extended_date_utc = None
                        extended_date_utc = datetime.now(todoist_tz).astimezone(pytz.utc).replace(hour=21, minute=59, second=59)

                        # extend duration of event before ticking it
                        try:
                            self.date_google(cal_id, None, todoist_item['id'], \
                                todoist_item['content'], event_id,  extended_date_utc)
                        except Exception as err:
                            log.error(str(err) + '\nCould not update date of event in Gcal...' )

                        # restore event color from overdue color
                        self.__gcal.update_event_color(cal_id, event_id, None)

                event_name = '✓ ' + self.event_name(todoist_item, True)
                try:
                    if self.__gcal.update_event_summary(cal_id, event_id, event_name):
                        log.debug('Task ' + str(task_id) + ' has been completed.')
                        op_code = True
                    else:
                        log.error('We could not update event name to reflect completion of task \
                            in Todoist.')
                except Exception as err:
                    log.exception(err)

            # if could append tickmark to the front of Todoist
            if op_code:
                c.execute('''CREATE TABLE IF NOT EXISTS todoist_completed
                    (project_id integer, parent_project_id integer, task_id integer, due_date text,
                    event_id integer, overdue integer, times_overdue integer, times_resheduled_on_due_date integer)''')

                conn.commit()

                c.execute('''SELECT project_id integer, parent_project_id integer, task_id integer,
                    due_date text, event_id integer, overdue integer, times_overdue integer,
                    times_resheduled_on_due_date integer FROM todoist WHERE task_id = ?''',
                    (task_id,))

                row_data = c.fetchone()

                if row_data:
                    # to allow for undo functionality
                    c.executemany('INSERT INTO todoist_completed VALUES (?,?,?,?,?,?,?,?)', (row_data,))

                    conn.commit()

                    c.execute('''DELETE FROM todoist WHERE task_id = ?''', (task_id,))

                    conn.commit()

        if op_code:
            # remove popup reminder from event, since the event is completed
            self.__gcal.update_event_reminders(cal_id, event_id)

        return op_code

    def new_task_added(self, item, completed_due_utc=None):
        op_code = False

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS todoist
                (project_id integer, parent_project_id integer, task_id integer, due_date text,
                event_id integer, overdue integer, times_overdue integer, times_resheduled_on_due_date integer)''')

            # 'todoist_completed' must be created at the same time so that is_complete
            # does not fail at runtime
            c.execute('''CREATE TABLE IF NOT EXISTS todoist_completed
                (project_id integer, parent_project_id integer, task_id integer, due_date text,
                event_id integer, overdue integer, times_overdue integer, times_resheduled_on_due_date integer)''')

            include_task = True
            if item is not None:
                if self.__todoist.settings['projects.excluded']:
                    try:
                        c.execute("SELECT project_id FROM excluded_ids WHERE project_id = ?", \
                            (item['project_id'],))
                    except sqlite3.OperationalError:
                        pass

                    # if project of task is excluded
                    if c.fetchone():
                        include_task = False

                # prevent duplicates
                # if not recurring, check tables "todoist" and "todoist_completed" for task_id
                if include_task and not 'every' in item['date_string'].lower():
                    try:
                        c.execute("SELECT due_date FROM todoist_completed WHERE task_id = ?", \
                            (item['id'],))
                    except sqlite3.OperationalError:
                        pass

                    if c.fetchone():
                        include_task = False
                    else:
                        try:
                            c.execute("SELECT due_date FROM todoist WHERE task_id = ?", \
                                (item['id'],))
                        except sqlite3.OperationalError:
                            pass

                        if c.fetchone():
                            include_task = False

                # prevent duplicates
                if include_task:
                    try:
                        c.execute("SELECT due_date FROM todoist_completed WHERE task_id = ?", \
                            (item['id'],))
                    except sqlite3.OperationalError:
                        pass

                    dates_from_completed = c.fetchall()
                    if dates_from_completed:
                        date_utc_str = self.__todoist.date_parser(item['due_date_utc'])
                        due_date_utc = datetime.strptime(date_utc_str, "%a %d %b %Y %H:%M:%S +0000").date()
                        for date in dates_from_completed:
                            date = self.__todoist.date_parser(date[0])

                            # convert str dates to date objects for comparison
                            table_date = datetime.strptime(date, "%a %d %b %Y %H:%M:%S +0000").date()

                            if table_date == due_date_utc:
                                include_task = False
                                break

                parent_id = self.__todoist.__parent_project_id__(item['project_id'])
                if include_task and parent_id and item['due_date_utc'] and item['project_id'] != self.__todoist.inbox_project_id:
                    due_date_utc = None
                    colorId = None
                    overdue = None
                    completed_date_utc = None

                    if not completed_due_utc:
                        due_date_utc = self.__todoist.__todoist_utc_to_date__(item['due_date_utc'])

                        # set overdue task's color to bold red and append a unicode icon to the front
                        task_due_date = self.__todoist.__todoist_utc_to_date__(item['due_date_utc'])

                        todoist_tz = pytz.timezone(self.timezone())
                        difference = (task_due_date - datetime.now(todoist_tz).date()).days
                        if difference < 0:
                            # if overdue and p2 --> slip to q1 in Todoist
                            todoist_item = self.__todoist.api.items.get_by_id(item['id'])
                            todoist_item.update(priority=4)
                            self.__todoist.api.commit()
                            colorId = 11
                            overdue = True
                    else:
                        completed_utc = datetime.strptime(completed_due_utc, "%a %d %b %Y %H:%M:%S +0000").date()
                        task_due_date_utc = datetime.strptime(item['due_date_utc'], "%a %d %b %Y %H:%M:%S +0000").date()
                        difference = abs((task_due_date_utc - completed_utc).days)

                        # events to be extended_utc
                        if completed_utc > task_due_date_utc and difference > 0 and difference < 3:
                            due_date_utc = self.__todoist.__todoist_utc_to_date__(item['due_date_utc'])
                            completed_date_utc = self.__todoist.__todoist_utc_to_date__(completed_due_utc)

                            # increment end date by one, for google calendar end date
                            completed_date_utc = completed_date_utc + timedelta(days=1)
                        else:
                            # add completed tasks to the date they were completed
                            due_date_utc = self.__todoist.__todoist_utc_to_date__(completed_due_utc)

                    event_start_datetime = self.__todoist.__date_to_google_format__(due_date_utc)
                    if completed_date_utc:
                        event_end_datetime = self.__todoist.__date_to_google_format__(completed_date_utc)
                    else:
                        event_end_datetime = None

                    event_location = self.task_path(item['id'])
                    cal_id = self.__todoist.find_cal_id(item['project_id'], parent_id)
                    event_name = self.event_name(item, completed_due_utc)
                    desc = self.event_desc(item)

                    # create all-day event for each task
                    try:
                        event_id = self.__gcal.insert_event(cal_id, event_name, event_start_datetime, \
                        event_end_datetime, event_location, desc, self.__todoist.todoist_user_tz, colorId)

                        item_due_date = None
                        if not completed_due_utc:
                            item_due_date = item['due_date_utc']
                        else:
                            item_due_date = completed_due_utc

                        if event_id:
                            todoist_item_info = [item['project_id'], parent_id, item['id'], \
                                str(item_due_date), event_id, overdue, None, None ]

                            c.executemany('INSERT INTO todoist VALUES (?,?,?,?,?,?,?,?)', (todoist_item_info,))
                            conn.commit()

                            op_code = True
                    except Exception as err:
                        log.exception(err)

            return op_code

    def task_location(self, calendar_id, event_id, task_id, project_id):
        op_code = False

        conn = sqlite3.connect('db/data.db')

        with conn:
            c = conn.cursor()

            parent_project_id = self.__todoist.__parent_project_id__(project_id)

            c.execute("SELECT project_id FROM todoist WHERE task_id = ? AND project_id = ? AND parent_project_id = ?",
                (task_id, project_id,parent_project_id,))

            # if project_id and parent_project_id did not change returns row of data, else
            # if task has been moved to another project or parent project, returns None
            data = c.fetchone()

            # if we have a new project_id, we may have a new parent_project_id as well
            # either the project_id or the parent_project_id or both are different
            if not data:
                event_location = self.task_path(task_id)

                cal_id = self.__todoist.find_cal_id(project_id, parent_project_id)

                try:
                    if self.__gcal.update_event_location(calendar_id, event_id, event_location, cal_id):
                        # calendar_id != destination calendar id
                        if calendar_id != cal_id:
                            # assume the .move() function was called
                            self.__todoist.changed_location_of_event = event_id
                        op_code = True

                        # update project_id and parent_project_id of db with the new data,
                        # so we can perform the move again
                        try:
                            c.execute("UPDATE todoist SET project_id = ?, parent_project_id = ? WHERE task_id = ?",
                                (parent_project_id, project_id , task_id,))
                            conn.commit()
                            op_code = True
                        except Exception as err:
                            log.error(str(err) + '\nCould update event date on Gcal, but could not update Todoist table.')
                except Exception as err:
                    log.exception(err)

        conn.close()

        return op_code

    def undo(self, task_id):
        conn = sqlite3.connect('db/data.db')

        c = conn.cursor()

        with conn:
            # move task data back to "todoist" table
            if self.__todoist.is_completed(task_id):
                c.execute('''SELECT project_id integer, parent_project_id integer, task_id integer,\
                    due_date text, event_id integer, overdue integer, times_overdue integer, \
                    times_resheduled_on_due_date integer  FROM todoist_completed \
                    WHERE task_id = ?''',(task_id,))

                data_row = c.fetchone()

            if data_row:
                c.executemany('INSERT INTO todoist VALUES (?,?,?,?,?,?,?,?)',(data_row,))

                conn.commit()

                c.execute('''DELETE FROM todoist_completed WHERE task_id = ?''', (task_id,))

                conn.commit()

                # find calendar_id of the task
                c.execute("SELECT calendar_id FROM gcal_ids WHERE todoist_project_id = ? OR todoist_project_id = ?",
                        (data_row[0],data_row[1],))

                # retrieve it
                calendar_id = c.fetchone()
                if calendar_id:
                    calendar_id = calendar_id[0]

                # sync date because if it was overdue and was stetched it won't go back to normal just like that
                try:
                    item = self.__todoist.api.items.get_by_id(task_id)
                    if item is not None:
                        self.date_google(calendar_id, item['due_date_utc'], task_id, item['content'], data_row[4])
                except Exception as err:
                    log.exception(str(err) + 'Could not update date of event in Gcal...')

                # call sync task name now that the data is back in the "todoist" table
                # task name --> event name (sync)
                # this has to be called after the code block above, so that icon priority is preserved
                try:
                    self.task_name(calendar_id, data_row[4], task_id)
                except Exception as err:
                    log.exception(err)

                try:
                    # add the reminder popup back, since the event got unticked
                    self.__gcal.update_event_reminders(calendar_id, data_row[4], 300)
                except Exception as err:
                    log.exception(str(err) + ' from updating event reminders in undo')

        conn.close()

    def task_path(self, task_id):
        """
            Compose the event location for each event added to Gcal.
        """

        event_location = ''
        if self.__todoist.premium_user:
            try:
                task_notes = self.__todoist.api.items.get(task_id)
                if task_notes and task_notes['notes']:
                    event_location = '✉ '
            except Exception as err:
                log.debug(err)

        item = self.__todoist.api.items.get_by_id(task_id)

        if item is not None and task_id:
            parent_id = self.__todoist.__parent_project_id__(item['project_id'])
            if parent_id is None:
                log.error("Todoist error: 'parent_id' of project " + str(item['project_id']) \
                + " is set to None.")

            # find the child project the task resides in
            project_of_item = self.__todoist.api.projects.get_by_id(item['project_id'])

            if parent_id and project_of_item != None and project_of_item['indent'] != 1:
                event_location += self.__todoist.api.projects.get_by_id(parent_id)['name'] \
                    + ', ' + project_of_item['name']
            elif project_of_item != None and project_of_item['indent'] == 1:
                event_location += project_of_item['name']
            parent_of_task = self.__todoist.api.items.get_by_id(item['id'])

            # append the name of the parent task to the location of the event of the sub-task
            if item['indent'] != 1 and item['parent_id'] != None:
                event_location += ', ' + parent_of_task['content']
        return event_location

    def update_desc_location(self, task_id):
        """
            Updates event description and location, due to a change in task's notes.
        """

        new_event_location = self.task_path(task_id)
        item = self.__todoist.api.items.get_by_id(task_id)
        new_desc = self.event_desc(item)

        parent_project_id = self.__todoist.__parent_project_id__(item['project_id'])
        cal_id = self.__todoist.find_cal_id(item['project_id'], parent_project_id)

        conn = sqlite3.connect('db/data.db')

        event_id = None
        with conn:
            c = conn.cursor()

            # find event id
            c.execute("SELECT project_id, parent_project_id, due_date, event_id FROM todoist \
                WHERE task_id = ?", (task_id,))

            task_data = c.fetchone()

            if task_data:
                event_id = task_data[3]
        conn.close()

        if event_id:
            self.__gcal.update_event_location(cal_id, event_id, new_event_location, cal_id)

            self.__gcal.update_event_desc(cal_id, event_id, new_desc)

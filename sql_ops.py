"""
File: sql_ops.py
Purpose: Perform sql operations on database (FOR INTERNAL USE ONLY).
Author: Alexandros Nicolaides
Dependencies:
"""

"""
    WARNING:
    Some practises used in this file shall not be used by public APIs due to security corcerns.
    This file is used internally, for convenience and code reusability.
"""

import sqlite3
import logging
import load_cfg

log = logging.getLogger(__name__)

def init_db():
    """ Creates tables by fetching info from 'db_schema.json'. """
    for table_name in load_cfg.DB_SCHEMA:
        for table_schema in load_cfg.DB_SCHEMA[table_name]:
            create_table(table_name, table_schema)

def create_table(table_name, table_schema):
    """ Create a table in the db using the args provided. """
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])

    with conn:
        c = conn.cursor()

        c.execute("CREATE TABLE IF NOT EXISTS " + table_name + " (" + table_schema + ")")

        conn.commit()

def truncate_table(table_name):
    """ Truncates table provided. """
    truncated = True
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])

    with conn:
        c = conn.cursor()

        try:
            c.execute("DELETE FROM " + table_name)
            conn.commit()
        except Exception as err:
            truncated = False
            log.exception(err)
    return truncated

def delete_from_where(table_name, column_name, condition):
    """ Returns true upon successful deletion, otherwise false. """
    deleted = True
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])

    with conn:
        c = conn.cursor()

        try:
            c.execute("DELETE FROM " + table_name + " WHERE " + column_name + "=?", (condition,))
            conn.commit()
        except sqlite3.OperationalError as err:
            deleted = False
            log.exception(err)
    return deleted

def select_from_where(select_operand, table_name, where_operand=None, condition=None, fetch_all=False, cursor=False, *args):
    """ Returns data upon successful retrieval from db. """
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])
    data = None
    with conn:
        c = conn.cursor()

        try:
            if where_operand is None and condition is None:
                c.execute("SELECT " + select_operand + " FROM " + table_name)
            elif where_operand and condition is None and not args:
                c.execute("SELECT " + select_operand + " FROM " + table_name + " WHERE " + where_operand)
            elif where_operand and condition:
                c.execute("SELECT " + select_operand + " FROM " + table_name + " WHERE " + where_operand + "=?", (condition,))
            else:
                c.execute("SELECT " + select_operand + " FROM " + table_name + " WHERE " + where_operand, args)
        except sqlite3.OperationalError as err:
            log.exception(err)

        if fetch_all:
            data = c.fetchall()
        else:
            data = c.fetchone()
    return data

def insert(table_name, *args):
    """ Inserts data to table. """
    insertion = True
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])

    with conn:
        c = conn.cursor()

        questionmarks = generate_args(len(args))

        try:
            c.execute("INSERT INTO " + table_name + " VALUES (" + questionmarks + ")", args)
            conn.commit()
        except sqlite3.OperationalError as err:
            insertion = False
            log.exception(err)
    return insertion

def insert_many(table_name, row_data):
    """ Inserts row of data to table. """
    insertion = True
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])

    with conn:
        c = conn.cursor()

        questionmarks = generate_args(len(row_data))
        try:
            c.executemany("INSERT INTO " + table_name + " VALUES (" + questionmarks + ")", (row_data,))
            conn.commit()
        except sqlite3.OperationalError as err:
            insertion = False
            log.exception(err)
    return insertion

def update_set_where(table_name, columns, where_operand, *args):
    """ Updates table based on some conditions. """
    updated = True
    conn = sqlite3.connect(load_cfg.USER_PREFS['db.path'])

    with conn:
        c = conn.cursor()

        try:
            c.execute("UPDATE " + table_name + " SET " + columns + " WHERE " + where_operand + " = ? ", args)
            conn.commit()
        except sqlite3.OperationalError as err:
            updated = False
            log.exception(err)
    return updated

def generate_args(num):
    """ Returns questionmarks separated by commas as a string to be used by the insert command. """
    args_str = ''
    for i in range(0, num):
        if i == num - 1:
            args_str += '?'
        else:
            args_str += '?,'
    return args_str
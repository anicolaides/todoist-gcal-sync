"""
File: mylogging.py
Purpose: Configure logging for the project.
Author: Alexandros Nicolaides
Dependencies:
"""

import logging
import logging.config
import logging.handlers
import time
import queue
import json
import atexit

my_queue = queue.Queue(-1)

class UTCFormatter(logging.Formatter):
    converter = time.gmtime

class MyFilter():
    def __init__(self, op, level):
        self.__level = logging._checkLevel(level)
        self.__operator = op

    def filter(self, logRecord):
        return self.__operator(logRecord.levelno, self.__level)


with open('config/log_cfg.json', mode='r') as config:
    logging.config.dictConfig(json.load(config))

q_listener = logging.handlers.QueueListener(my_queue, \
        logging.config.logging._handlers['consoleHandler'], \
        logging.config.logging._handlers['debug_file_handler'], \
        logging.config.logging._handlers['info_file_handler'], \
        logging.config.logging._handlers['err_file_handler'], \
        logging.config.logging._handlers['mail_handler'])

q_listener.start()

atexit.register(q_listener.stop)

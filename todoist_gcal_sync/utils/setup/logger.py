"""
Configures logging for the project.

Dependencies:
"""

import os
import logging
import logging.config
import logging.handlers
import queue
import atexit
from todoist_gcal_sync.utils.setup.helper import load_json, CREDS_DIR_PATH, LOGS_DIR_PATH, MAIL_SMTP_FILE_NAME
from todoist_gcal_sync.utils.setup.helper import DEBUG_LOG_FILE_PATH, INFO_LOG_FILE_PATH, ERROR_LOG_FILE_PATH
from todoist_gcal_sync.utils.setup.CustomQueueListener import CustomQueueListener
from todoist_gcal_sync.utils.setup.log_cfg_extras import UTCFormatter, MyFilter

__author__ = "Alexandros Nicolaides"
__status__ = "production"

my_queue = queue.Queue(-1)

if not os.path.exists(LOGS_DIR_PATH):
    try:
        os.mkdir(LOGS_DIR_PATH)
    except FileExistsError as err:
        print("Could not create the logs dir.")

logging_cfg = dict({
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "standard": {
            "()": UTCFormatter,
            "format": "%(asctime)s  %(levelname)-8s %(filename)s:%(funcName)s:%(lineno)d  %(message)s"
        }
    },
    "filters": {
        "debug_filter": {
            "()": MyFilter,
            "op": "ext://operator.eq",
            "level": "DEBUG"
        },
        "info_filter": {
            "()": MyFilter,
            "op": "ext://operator.eq",
            "level": "INFO"
        },
        "warning_filter": {
            "()": MyFilter,
            "op": "ext://operator.ge",
            "level": "WARNING"
        }
    },
    "handlers": {
        "consoleHandler": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "standard",
            "stream": "ext://sys.stdout"
        },
        "debug_file_handler": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "DEBUG",
            "formatter": "standard",
            "filename": DEBUG_LOG_FILE_PATH,
            "when": "d",
            "interval": 14,
            "backupCount": 2,
            "encoding": "utf-8",
            "utc": True,
            "filters": [
                "debug_filter"
            ]
        },
        "info_file_handler": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": INFO_LOG_FILE_PATH,
            "when": "d",
            "interval": 14,
            "backupCount": 2,
            "encoding": "utf-8",
            "utc": True,
            "filters": [
                "info_filter"
            ]
        },
        "err_file_handler": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "WARNING",
            "formatter": "standard",
            "filename": ERROR_LOG_FILE_PATH,
            "when": "d",
            "interval": 14,
            "backupCount": 2,
            "encoding": "utf-8",
            "utc": True,
            "filters": [
                "warning_filter"
            ]
        },
        "q_handler": {
            "class": "logging.handlers.QueueHandler",
            "queue": my_queue
        }
    },
    "loggers": {
        "": {
            "level": "WARNING",
            "handlers": [
                "q_handler"
            ]
        },
        "__main__": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "todo": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "todoist_auth": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "todoist_sync": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "gcal": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "load_cfg": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "gcal_OAuth": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "gcal_sync": {
            "level": "DEBUG",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        },
        "googleapiclient.discovery": {
            "level": "WARNING",
            "handlers": [
                "q_handler"
            ],
            "propagate": False
        }
    }
})


mail_handler = False
if os.path.exists(CREDS_DIR_PATH + MAIL_SMTP_FILE_NAME):
    mail_handler = True
    smtp_creds = load_json(MAIL_SMTP_FILE_NAME, CREDS_DIR_PATH)

    logging_cfg['handlers']['mail_handler'] = {
        "class": "logging.handlers.SMTPHandler",
        "level": "WARNING",
        "formatter": "standard",
        "mailhost": ["smtp.gmail.com", 587],
        "fromaddr": smtp_creds['from'],
        "toaddrs": smtp_creds['to'],
        "subject": "Error found!",
        "credentials": [smtp_creds['email'], smtp_creds['one_time_app_password']],
        "secure": [],
        "filters": ["warning_filter"]
    }

logging.config.dictConfig(logging_cfg)

q_listener = CustomQueueListener(my_queue,
                                 logging.config.logging._handlers['consoleHandler'],
                                 logging.config.logging._handlers['debug_file_handler'],
                                 logging.config.logging._handlers['info_file_handler'],
                                 logging.config.logging._handlers['err_file_handler'])

if mail_handler:
    q_listener.addHandler(logging.config.logging._handlers['mail_handler'])

q_listener.start()

atexit.register(q_listener.stop)

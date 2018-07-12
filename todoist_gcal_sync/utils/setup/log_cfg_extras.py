import time
import logging


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


class MyFilter():
    def __init__(self, op, level):
        self.__level = logging._checkLevel(level)
        self.__operator = op

    def filter(self, logRecord):
        return self.__operator(logRecord.levelno, self.__level)

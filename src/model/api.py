
import logging
import time
import fcall


class API(fcall.APIBase):
    def __init__(self, env):
        super(API, self).__init__()
        self.env = env

    def log(self, text):
        logging.warn(text)

    def sleep(self, period):
        time.sleep(period)

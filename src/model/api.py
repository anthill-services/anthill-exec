import logging
from lazy import lazy
import datetime

from fcall import APIBase, deferred
from tornado.gen import coroutine, Return, sleep
from common.access import Internal


class API(APIBase):
    def __init__(self, future, env, ioloop):
        super(API, self).__init__(future)
        self.env = env
        self.ioloop = ioloop

    @deferred
    @coroutine
    def get_my_profile(self, path="", *ignored):
        internal = Internal()
        profile = yield internal.request("profile", "get_my_profile",
                                         gamespace_id=self.env["gamespace"],
                                         account_id=self.env["account"],
                                         path=path)

        raise Return(profile)

    def log(self, text, *ignored):
        logging.info(text)

    @deferred
    @coroutine
    def sleep(self, period, *ignored):
        yield sleep(period)

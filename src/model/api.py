import logging
from lazy import lazy
import datetime

from fcall import APIBase, APIError, deferred, convert
from tornado.gen import coroutine, Return, sleep
from common.access import Internal


class API(APIBase):
    def __init__(self, future, env, ioloop, debug):
        super(API, self).__init__(future, debug)
        self.env = env
        self.ioloop = ioloop

    def log(self, data, *ignored):
        super(API, self).log("JS: gs #{0} acc @{1} {2}".format(
            self.env["gamespace"],
            self.env["account"],
            data), *ignored)

    @deferred
    @coroutine
    def get_my_profile(self, path="", *ignored):
        internal = Internal()
        profile = yield internal.request("profile", "get_my_profile",
                                         gamespace_id=self.env["gamespace"],
                                         account_id=self.env["account"],
                                         path=path)

        raise Return(profile)

    @deferred
    @coroutine
    def update_my_profile(self, profile=None, path="", merge=True, *ignored):

        if not profile:
            profile = {}
        else:
            profile = convert(profile)

        if not isinstance(path, (unicode, str)):
            raise APIError(code=400, message="Path should be a string")

        internal = Internal()
        profile = yield internal.request("profile", "update_profile",
                                         gamespace_id=self.env["gamespace"],
                                         account_id=self.env["account"],
                                         fields=profile,
                                         path=path,
                                         merge=merge)

        raise Return(profile)

    @deferred
    @coroutine
    def sleep(self, period, *ignored):
        yield sleep(period)

import logging
from lazy import lazy
import datetime

from fcall import APIBase, APIError, deferred, convert
from tornado.gen import coroutine, engine, Return, sleep
from common.access import Internal
from expiringdict import ExpiringDict


class API(APIBase):
    def __init__(self, env, debug, callback):
        super(API, self).__init__(debug, callback)

        self.env = env
        self.profile_cache = ExpiringDict(10, 60)

    def log(self, message, *ignored):
        logging.info("JS: gs #{0} acc @{1} {2}".format(
            self.env["gamespace"],
            self.env["account"],
            message))
        super(API, self).log(message)

    @deferred
    def get_my_profile(self, path="", *ignored):

        cached = self.profile_cache.get(path)

        if cached:
            raise Return(cached)

        internal = Internal()
        profile = yield internal.request("profile", "get_my_profile",
                                         gamespace_id=self.env["gamespace"],
                                         account_id=self.env["account"],
                                         path=path)

        self.profile_cache[path] = profile

        raise Return(profile)

    @deferred
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

        self.profile_cache[path] = profile

        raise Return(profile)

    @deferred
    def sleep(self, period, *ignored):
        yield sleep(period)

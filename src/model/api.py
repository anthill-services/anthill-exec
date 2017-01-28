import logging

from fcall import APIBase, APIError, deferred, DeferredAPI
from tornado.gen import coroutine, Return, sleep
from common.internal import Internal, InternalError


class ConfigAPI(DeferredAPI):
    def __init__(self, api, context):
        super(ConfigAPI, self).__init__(api, context)
        self.internal = Internal()

    @deferred
    def get(self, app_name, app_version, *ignored):

        if not isinstance(app_name, (unicode, str)):
            raise APIError(code=400, message="app_name should be a string")
        if not isinstance(app_version, (unicode, str)):
            raise APIError(code=400, message="app_version should be a string")

        obj = self._context.obj

        key = "config:" + str(app_name) + "/" + str(app_version)

        cached = obj.cache.get(key)

        if cached:
            raise Return(cached)

        try:
            config = yield self.internal.request(
                "config", "get_configuration",
                gamespace=obj.env["gamespace"],
                app_name=app_name,
                app_version=app_version)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = config

        raise Return(config)


class ProfileAPI(DeferredAPI):
    def __init__(self, api, context):
        super(ProfileAPI, self).__init__(api, context)
        self.internal = Internal()

    @deferred
    def get(self, path="", *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(code=400, message="Path should be a string")

        obj = self._context.obj

        key = "profile:" + str(path)

        cached = obj.cache.get(key)

        if cached:
            raise Return(cached)

        try:
            profile = yield self.internal.request(
                "profile", "get_my_profile",
                gamespace_id=obj.env["gamespace"],
                account_id=obj.env["account"],
                path=path)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = profile

        raise Return(profile)

    @deferred
    def update(self, profile=None, path="", merge=True, *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(code=400, message="Path should be a string")

        obj = self._context.obj

        key = "profile:" + str(path)

        if not profile:
            profile = {}

        try:
            profile = yield self.internal.request(
                "profile", "update_profile",
                gamespace_id=obj.env["gamespace"],
                account_id=obj.env["account"],
                fields=profile,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = profile

        raise Return(profile)


class API(APIBase):
    def __init__(self, context, debug, callback):
        super(API, self).__init__(context, debug, callback)

        self.env = context.obj.env
        self.profile = ProfileAPI(self, context)
        self.config = ConfigAPI(self, context)

    def log(self, message, *ignored):
        logging.info("JS: gs #{0} acc @{1} {2}".format(
            self.env["gamespace"],
            self.env["account"],
            message))
        super(API, self).log(message)

    @deferred
    def sleep(self, period, *ignored):
        yield sleep(period)

AUTOCOMPLETE_LIST = [
    "throw error",
    "api.res",
    "api.sleep",
    "api.log",
    "api.profile.get",
    "api.profile.update",
    "api.config.get"
]

import logging
import ujson

from fcall import APIBase, APIError, deferred, DeferredAPI, Deferred
from tornado.gen import coroutine, Return, sleep, Future
from common.internal import Internal, InternalError


API_TIMEOUT = 5


class ConfigAPI(DeferredAPI):
    def __init__(self, api, context, worker):
        super(ConfigAPI, self).__init__(api, context, worker)
        self.internal = Internal()

    @deferred
    def get(self, app_version, *ignored):

        if not isinstance(app_version, (unicode, str)):
            raise APIError(code=400, message="app_version should be a string")

        obj = self._context.obj

        app_name = obj.env["application_name"]

        key = "config:" + str(app_name) + "/" + str(app_version)

        cached = obj.cache.get(key)

        if cached:
            raise Return([cached])

        try:
            config = yield self.internal.request(
                "config", "get_configuration",
                timeout=API_TIMEOUT,
                app_name=app_name,
                app_version=app_version)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = config

        raise Return([config])


class StoreAPI(DeferredAPI):
    def __init__(self, api, context, worker):
        super(StoreAPI, self).__init__(api, context, worker)
        self.internal = Internal()

    @deferred
    def get(self, name, *ignored):

        if not isinstance(name, (unicode, str)):
            raise APIError(code=400, message="name should be a string")

        obj = self._context.obj

        key = "store:" + str(name)

        cached = obj.cache.get(key)

        if cached:
            raise Return([cached])

        try:
            config = yield self.internal.request(
                "store", "get_store",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = config

        raise Return([config])

    @deferred
    def new_order(self, store, item, currency, amount, component, *ignored):
        obj = self._context.obj

        try:
            result = yield self.internal.request(
                "store", "new_order",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                account=obj.env["account"],
                store=store,
                item=item,
                currency=currency,
                amount=amount,
                component=component)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([result])

    @deferred
    def update_order(self, order_id, *ignored):
        obj = self._context.obj

        try:
            result = yield self.internal.request(
                "store", "update_order",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                account=obj.env["account"],
                order_id=order_id)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([result])

    @deferred
    def update_orders(self, *ignored):
        obj = self._context.obj

        try:
            result = yield self.internal.request(
                "store", "update_orders",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                account=obj.env["account"])
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([result])


class ProfileAPI(DeferredAPI):
    def __init__(self, api, context, worker):
        super(ProfileAPI, self).__init__(api, context, worker)
        self.internal = Internal()

    @deferred
    def get(self, path="", *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(code=400, message="Path should be a string")

        obj = self._context.obj

        key = "profile:" + str(path)

        cached = obj.cache.get(key)

        if cached:
            raise Return([cached])

        try:
            profile = yield self.internal.request(
                "profile", "get_my_profile",
                timeout=API_TIMEOUT,
                gamespace_id=obj.env["gamespace"],
                account_id=obj.env["account"],
                path=path)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = profile

        raise Return([profile])

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
                timeout=API_TIMEOUT,
                gamespace_id=obj.env["gamespace"],
                account_id=obj.env["account"],
                fields=profile,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        obj.cache[key] = profile

        raise Return([profile])


class SocialAPI(DeferredAPI):
    def __init__(self, api, context, worker):
        super(SocialAPI, self).__init__(api, context, worker)
        self.internal = Internal()

    @deferred
    def update_profile(self, group_id, profile=None, path=None, merge=True, *ignored):

        if path and not isinstance(path, (list, tuple)):
            raise APIError(code=400, message="Path should be a list/tuple")

        obj = self._context.obj

        try:
            profile = yield self.internal.request(
                "social", "update_group_profile",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                group_id=group_id,
                profile=profile,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([profile])

    @deferred
    def update_group_profiles(self, group_profiles, path=None, merge=True, *ignored):

        if not isinstance(group_profiles, dict):
            raise APIError(code=400, message="Group profiles should be a dict")

        if path and not isinstance(path, (list, tuple)):
            raise APIError(code=400, message="Path should be a list/tuple")

        obj = self._context.obj

        try:
            profile = yield self.internal.request(
                "social", "update_group_profiles",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                group_profiles=group_profiles,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([profile])


class MessageAPI(DeferredAPI):
    def __init__(self, api, context, worker):
        super(MessageAPI, self).__init__(api, context, worker)
        self.internal = Internal()

    @deferred
    def send_batch(self, sender, messages, authoritative=True, *ignored):

        obj = self._context.obj

        try:
            yield self.internal.request(
                "message", "send_batch",
                timeout=API_TIMEOUT,
                gamespace=obj.env["gamespace"],
                sender=sender,
                messages=messages,
                authoritative=authoritative)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return(["OK"])


class API(APIBase):
    def __init__(self, context, callback, worker):
        super(API, self).__init__(context, callback)

        self._worker = worker

        self.env = context.obj.env
        self.profile = ProfileAPI(self, context, worker)
        self.config = ConfigAPI(self, context, worker)
        self.store = StoreAPI(self, context, worker)
        self.social = SocialAPI(self, context, worker)
        self.message = MessageAPI(self, context, worker)

    @deferred
    def parallel(self, *items):

        class Response(object):
            def __init__(self):
                self.success = None
                self.data = None
                self.code = None
                self.message = None

            def resolve(self, data=None, *ignored):
                self.success = True
                self.data = data

            def reject(self, code, message):
                self.success = False
                self.code = code
                self.message = message

        def prepare(item):
            if not isinstance(item, Deferred):
                raise APIError(400, "Item is not a deferred!")

            f = Future()
            item.done(lambda *args: f.set_result((True, args))).fail(lambda *args: f.set_result((False, args)))
            return f

        if len(items) == 1 and isinstance(items[0], list):
            items = items[0]

        futures = map(prepare, items)
        futures_result = yield futures

        def finalize(args):
            success, data = args
            response = Response()
            if success:
                response.resolve(*data)
            else:
                response.reject(*data)
            return response

        result = map(finalize, futures_result)
        raise Return(result)

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
    "api.config.get",
    "api.store.get"
]

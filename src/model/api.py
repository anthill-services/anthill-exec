
import tornado.gen

from util import deferred, Deferred, APIUserError, DeferredContext, APIError
from tornado.gen import coroutine, Return, sleep, Future
from common.internal import Internal, InternalError
import options as _opts


API_TIMEOUT = 5


@deferred
def sleep(delay, handler=None):
    yield tornado.gen.sleep(delay)


def log(message):
    handler = DeferredContext.current
    if handler:
        handler.log(message)


@deferred
def parallel(*items, **kwargs):

    class Response(object):
        def __init__(self):
            self._success = None
            self._data = None
            self._code = None
            self._message = None

        def resolve(self, data=None, *ignored):
            self._success = True
            self._data = data

        def reject(self, *args):
            self._success = False

            if len(args) >= 2:
                self._code = args[0]
                self._message = args[1]
            elif len(args) == 1:
                self._code = 500
                self._message = args[0]
            else:
                self._code = 500
                self._message = "Unknown"

        @property
        def success(self):
            return self._success

        @property
        def code(self):
            return self._code

        @property
        def data(self):
            return self._data

        @property
        def message(self):
            return self._message

    def prepare(item):
        if not isinstance(item, Deferred):
            raise APIError(400, "Item is not a deferred!")

        f = tornado.gen.Future()
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
    raise tornado.gen.Return(result)


def res(result=None):
    if DeferredContext.current:
        DeferredContext.current.res(result)


def error(*args):
    if len(args) >= 2:
        exception = APIUserError(args[0], args[1])
    elif len(args) >= 1 and isinstance(args[0], (Exception, str)):
        exception = APIUserError(500, str(args[0]))
    else:
        exception = APIUserError(500, "Internal Script Error")
    return exception


class ConfigAPI(object):

    @deferred
    def get(self, handler=None, *ignored):

        app_name = handler.env["application_name"]
        app_version = handler.env["application_version"]

        key = "config:" + str(app_name) + "/" + str(app_version)
        cached = handler.get_cache(key)
        if cached:
            raise Return([cached])

        internal = Internal()

        try:
            config = yield internal.request(
                "config", "get_configuration",
                timeout=API_TIMEOUT,
                app_name=app_name,
                app_version=app_version)
        except InternalError as e:
            raise APIError(e.code, e.body)

        handler.set_cache(key, config)
        raise Return([config])


class StoreAPI(object):

    @deferred
    def get(self, name, handler=None, *ignored):

        if not isinstance(name, (unicode, str)):
            raise APIError(code=400, message="name should be a string")

        key = "store:" + str(name)
        cached = handler.get_cache(key)
        if cached:
            raise Return([cached])

        internal = Internal()

        try:
            config = yield internal.request(
                "store", "get_store",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        handler.set_cache(key, config)
        raise Return([config])

    @deferred
    def new_order(self, store, item, currency, amount, component, handler=None, *ignored):

        internal = Internal()

        try:
            result = yield internal.request(
                "store", "new_order",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                store=store,
                item=item,
                currency=currency,
                amount=amount,
                component=component)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([result])

    @deferred
    def update_order(self, order_id, handler=None, *ignored):

        internal = Internal()

        try:
            result = yield internal.request(
                "store", "update_order",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                order_id=order_id)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([result])

    @deferred
    def update_orders(self, handler=None, *ignored):

        internal = Internal()

        try:
            result = yield internal.request(
                "store", "update_orders",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"])
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([result])


class ProfileAPI(object):

    @deferred
    def get(self, path="", handler=None, *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(code=400, message="Path should be a string")

        key = "profile:" + str(path)
        cached = handler.get_cache(key)
        if cached:
            raise Return([cached])

        internal = Internal()

        try:
            profile = yield internal.request(
                "profile", "get_my_profile",
                timeout=API_TIMEOUT,
                gamespace_id=handler.env["gamespace"],
                account_id=handler.env["account"],
                path=path)
        except InternalError as e:
            raise APIError(e.code, e.body)

        handler.set_cache(key, profile)
        raise Return([profile])

    @deferred
    def update(self, profile=None, path="", merge=True, handler=None, *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(code=400, message="Path should be a string")

        key = "profile:" + str(path)
        if not profile:
            profile = {}

        internal = Internal()

        try:
            profile = yield internal.request(
                "profile", "update_profile",
                timeout=API_TIMEOUT,
                gamespace_id=handler.env["gamespace"],
                account_id=handler.env["account"],
                fields=profile,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        handler.set_cache(key, profile)
        raise Return([profile])


class SocialAPI(object):

    @deferred
    def acquire_name(self, kind, name, handler=None, *ignored):
        internal = Internal()

        try:
            profile = yield internal.request(
                "social", "acquire_name",
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                kind=kind,
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([profile])

    @deferred
    def check_name(self, kind, name, handler=None, *ignored):
        internal = Internal()

        try:
            account_id = yield internal.request(
                "social", "check_name",
                gamespace=handler.env["gamespace"],
                kind=kind,
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([account_id])

    @deferred
    def release_name(self, kind, handler=None, *ignored):
        internal = Internal()

        try:
            released = yield internal.request(
                "social", "release_name",
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                kind=kind)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([released])

    @deferred
    def update_profile(self, group_id, profile=None, path=None, merge=True, handler=None, *ignored):
        if path and not isinstance(path, (list, tuple)):
            raise APIError(code=400, message="Path should be a list/tuple")

        internal = Internal()

        try:
            profile = yield internal.request(
                "social", "update_group_profile",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                group_id=group_id,
                profile=profile,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return([profile])

    @deferred
    def update_group_profiles(self, group_profiles, path=None, merge=True, synced=False, handler=None, *ignored):
        if not isinstance(group_profiles, dict):
            raise APIError(code=400, message="Group profiles should be a dict")

        if path and not isinstance(path, (list, tuple)):
            raise APIError(code=400, message="Path should be a list/tuple")

        internal = Internal()

        try:
            profile = yield internal.request(
                "social", "update_group_profiles",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                group_profiles=group_profiles,
                path=path,
                merge=merge,
                synced=synced)
        except InternalError as e:
            raise APIError(e.code, e.body)
        raise Return([profile])


class MessageAPI(object):

    @deferred
    def send_batch(self, sender, messages, authoritative=True, handler=None, *ignored):

        internal = Internal()

        try:
            yield internal.request(
                "message", "send_batch",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                sender=sender,
                messages=messages,
                authoritative=authoritative)
        except InternalError as e:
            raise APIError(e.code, e.body)
        raise Return(["OK"])


class PromoAPI(object):

    @deferred
    def use_code(self, key, handler=None, *ignored):

        internal = Internal()

        try:
            result = yield internal.request(
                "promo", "use_code",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                key=key)
        except InternalError as e:
            raise APIError(e.code, e.body)

        try:
            result = result["result"]
        except KeyError:
            raise APIError(500, "Response had no 'result' field.")

        raise Return([result])


class CompletedDeferred(object):
    def __init__(self, success, code=0, message=None):
        self.success = success
        self.code = code
        self.message = message

    def done(self, func):
        if self.success is True:
            func(True)
        return self

    def fail(self, func):
        if self.success is not True:
            func(self.code, self.message)
        return self


def completed(success, code=0, message=None):
    return CompletedDeferred(success, code, message)


class APIS(object):
    config = ConfigAPI()
    store = StoreAPI()
    profile = ProfileAPI()
    social = SocialAPI()
    message = MessageAPI()
    promo = PromoAPI()


def expose(context):
    context.expose_readonly(
        log=log,
        sleep=sleep,
        parallel=parallel,
        completed=completed,

        config=APIS.config,
        store=APIS.store,
        profile=APIS.profile,
        social=APIS.social,
        message=APIS.message,
        promo=APIS.promo,

        error=error,
        res=res)

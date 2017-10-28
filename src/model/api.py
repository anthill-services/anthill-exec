
import tornado.gen

from tornado.gen import Return, sleep
from tornado.httpclient import HTTPRequest, HTTPError
from tornado.simple_httpclient import SimpleAsyncHTTPClient

# noinspection PyUnresolvedReferences
import options as _opts
from common.internal import Internal, InternalError
from util import promise, APIUserError, PromiseContext, APIError

API_TIMEOUT = 5


# noinspection PyUnusedLocal
@promise
def sleep(delay, handler=None):
    yield tornado.gen.sleep(delay)


def log(message):
    handler = PromiseContext.current
    if handler:
        handler.log(message)


# noinspection PyUnusedLocal
class WebAPI(object):
    def __init__(self):
        self.http_client = SimpleAsyncHTTPClient()

    @promise
    def get(self, url, headers=None, *args, **kwargs):
        request = HTTPRequest(url=url, use_gzip=True, headers=headers)

        try:
            response = yield self.http_client.fetch(request)
        except HTTPError as e:
            raise APIError(e.code, e.message)

        body = response.body

        raise Return(body)


# noinspection PyUnusedLocal
class ConfigAPI(object):

    @promise
    def get(self, handler=None, *ignored):

        app_name = handler.env["application_name"]
        app_version = handler.env["application_version"]

        internal = Internal()

        try:
            info = yield internal.request(
                "config", "get_configuration",
                timeout=API_TIMEOUT,
                app_name=app_name,
                app_version=app_version,
                gamespace=handler.env["gamespace"])
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return(info)


# noinspection PyUnusedLocal
class StoreAPI(object):

    @promise
    def get(self, name, handler=None, *ignored):

        if not isinstance(name, (unicode, str)):
            raise APIError(400, "name should be a string")

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
        raise Return(config)

    @promise
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

        raise Return(result)

    @promise
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

        raise Return(result)

    @promise
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

        raise Return(result)


# noinspection PyUnusedLocal
class ProfileAPI(object):

    @promise
    def get(self, path="", handler=None, *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(400, "Path should be a string")

        key = "profile:" + str(path)
        cached = handler.get_cache(key)
        if cached:
            raise Return(cached)

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
        raise Return(profile)

    @promise
    def update(self, profile=None, path="", merge=True, handler=None, *ignored):

        if not isinstance(path, (unicode, str)):
            raise APIError(400, "Path should be a string")

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
        raise Return(profile)


# noinspection PyUnusedLocal
class SocialAPI(object):

    @promise
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

        raise Return(profile)

    @promise
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

        raise Return(account_id)

    @promise
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

        raise Return(released)

    @promise
    def update_profile(self, group_id, profile=None, path=None, merge=True, handler=None, *ignored):
        if path and not isinstance(path, (list, tuple)):
            raise APIError(400, "Path should be a list/tuple")

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

        raise Return(profile)

    @promise
    def update_group_profiles(self, group_profiles, path=None, merge=True, synced=False, handler=None, *ignored):
        if not isinstance(group_profiles, dict):
            raise APIError(400, "Group profiles should be a dict")

        if path and not isinstance(path, (list, tuple)):
            raise APIError(400, "Path should be a list/tuple")

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

        raise Return(profile)


# noinspection PyUnusedLocal
class MessageAPI(object):

    @promise
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
        raise Return("OK")


# noinspection PyUnusedLocal
class PromoAPI(object):

    @promise
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

        raise Return(result)


class APIS(object):
    config = ConfigAPI()
    store = StoreAPI()
    profile = ProfileAPI()
    social = SocialAPI()
    message = MessageAPI()
    promo = PromoAPI()
    web = WebAPI()


def expose(context):
    context.expose_readonly(
        log=log,
        sleep=sleep,

        web=APIS.web,
        config=APIS.config,
        store=APIS.store,
        profile=APIS.profile,
        social=APIS.social,
        message=APIS.message,
        promo=APIS.promo,

        Error=APIUserError)

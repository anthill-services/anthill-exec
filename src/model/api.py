
import tornado.gen

from tornado.gen import Return, sleep, Future
from tornado.httpclient import HTTPRequest, HTTPError, AsyncHTTPClient
from tornado.simple_httpclient import SimpleAsyncHTTPClient

# noinspection PyUnresolvedReferences
import options as _opts
from common.internal import Internal, InternalError
from common.validate import validate_value
from common.server import Server
from util import promise, PromiseContext, APIError

API_TIMEOUT = 5


# noinspection PyUnusedLocal
@promise
def sleep(delay, handler=None):
    yield tornado.gen.sleep(delay)


# noinspection PyUnusedLocal
@promise
def moment(handler=None):
    yield tornado.gen.moment


def log(message):
    handler = PromiseContext.current
    if handler:
        handler.log(message)


class AdminAPI(object):
    @promise
    def delete_accounts(self, accounts, gamespace_only=True, handler=None, *args, **kwargs):
        application = Server.instance()

        publisher = yield application.acquire_publisher()

        yield publisher.publish("DEL", {
            "gamespace": handler.env["gamespace"],
            "accounts": accounts,
            "gamespace_only": gamespace_only
        })


# noinspection PyUnusedLocal
class WebAPI(object):
    def __init__(self):
        self.http_client = SimpleAsyncHTTPClient()
        self.rc_cache = {}

    @promise
    def get(self, url, headers=None, *args, **kwargs):
        request = HTTPRequest(url=url, use_gzip=True, headers=headers)

        existing_futures = self.rc_cache.get(url, None)

        if existing_futures is not None:
            future = Future()
            existing_futures.append(future)
            result = yield future
            raise Return(result)

        new_futures = []
        self.rc_cache[url] = new_futures

        try:
            response = yield self.http_client.fetch(request)
        except HTTPError as e:
            e = APIError(e.code, e.message)

            for future in new_futures:
                future.set_exception(e)

            del self.rc_cache[url]
            raise e
        else:
            body = response.body

            for future in new_futures:
                future.set_result(body)

            del self.rc_cache[url]

        raise Return(body)


# noinspection PyUnusedLocal
class ConfigAPI(object):
    @promise
    def get(self, handler=None, *ignored):

        app_name = handler.env["application_name"]
        app_version = handler.env["application_version"]

        key = "config:" + str(app_name) + ":" + str(app_version)
        cached = handler.get_cache(key)
        if cached:
            raise Return(cached)

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

        handler.set_cache(key, info)
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
    def new_order(self, store, item, currency, amount, component, env=None, handler=None, *ignored):

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
                component=component,
                env=env)
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

    @promise
    def query(self, query, limit=1000, handler=None, *ignored):

        if not validate_value(query, "json_dict"):
            raise APIError(400, "Query should be a JSON object")

        internal = Internal()

        try:
            results = yield internal.request(
                "profile", "query_profiles",
                timeout=API_TIMEOUT,
                gamespace_id=handler.env["gamespace"],
                query=query,
                limit=limit)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return(results)


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


class EventAPI(object):
    @promise
    def update_event_profile(self, event_id, profile, path=None, merge=True, handler=None):
        internal = Internal()

        try:
            events = yield internal.request(
                "event", "update_event_profile",
                event_id=event_id,
                profile=profile,
                path=path,
                merge=merge,
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"])
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return(events)

    @promise
    def list(self, extra_start_time=0, extra_end_time=0, handler=None):
        internal = Internal()

        try:
            events = yield internal.request(
                "event", "get_list",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                extra_start_time=extra_start_time,
                extra_end_time=extra_end_time)
        except InternalError as e:
            raise APIError(e.code, e.body)

        raise Return(events)


class APIS(object):
    config = ConfigAPI()
    store = StoreAPI()
    profile = ProfileAPI()
    social = SocialAPI()
    message = MessageAPI()
    promo = PromoAPI()
    web = WebAPI()
    event = EventAPI()
    admin = AdminAPI()


def expose(context, is_server=False):

    expose_objects = {
        "log": log,
        "sleep": sleep,
        "moment": moment,
        "web": APIS.web,
        "config": APIS.config,
        "store": APIS.store,
        "profile": APIS.profile,
        "social": APIS.social,
        "message": APIS.message,
        "promo": APIS.promo,
        "event": APIS.event
    }

    if is_server:
        expose_objects.update({
            "admin": APIS.admin
        })

    context.expose_readonly(**expose_objects)

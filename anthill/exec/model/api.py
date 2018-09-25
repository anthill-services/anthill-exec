
import tornado.gen

from tornado.gen import sleep, Future
from tornado.httpclient import HTTPRequest, HTTPError
from tornado.simple_httpclient import SimpleAsyncHTTPClient

from .. import options as _opts
from anthill.common.internal import Internal, InternalError
from anthill.common.validate import validate_value
from anthill.common.server import Server
from . util import promise, PromiseContext, APIError

API_TIMEOUT = 5


# noinspection PyUnusedLocal
@promise
async def sleep(delay, handler=None):
    await tornado.gen.sleep(delay)


# noinspection PyUnusedLocal
@promise
async def moment(handler=None):
    await tornado.gen.moment


def log(message):
    handler = PromiseContext.current
    if handler:
        handler.log(message)


class AdminAPI(object):
    @promise
    async def delete_accounts(self, accounts, gamespace_only=True, handler=None, *args, **kwargs):
        application = Server.instance()

        publisher = await application.acquire_publisher()

        await publisher.publish("DEL", {
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
    async def get(self, url, headers=None, *args, **kwargs):
        request = HTTPRequest(url=url, use_gzip=True, headers=headers)

        existing_futures = self.rc_cache.get(url, None)

        if existing_futures is not None:
            future = Future()
            existing_futures.append(future)
            result = await future
            return result

        new_futures = []
        self.rc_cache[url] = new_futures

        try:
            response = await self.http_client.fetch(request)
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

        return body


# noinspection PyUnusedLocal
class ConfigAPI(object):
    @promise
    async def get(self, handler=None, *ignored):

        app_name = handler.env["application_name"]
        app_version = handler.env["application_version"]

        key = "config:" + str(app_name) + ":" + str(app_version)
        cached = handler.get_cache(key)
        if cached:
            return cached

        internal = Internal()

        try:
            info = await internal.request(
                "config", "get_configuration",
                timeout=API_TIMEOUT,
                app_name=app_name,
                app_version=app_version,
                gamespace=handler.env["gamespace"])
        except InternalError as e:
            raise APIError(e.code, e.body)

        handler.set_cache(key, info)
        return info


# noinspection PyUnusedLocal
class StoreAPI(object):

    @promise
    async def get(self, name, handler=None, *ignored):

        if not isinstance(name, str):
            raise APIError(400, "name should be a string")

        key = "store:" + str(name)
        cached = handler.get_cache(key)
        if cached:
            return [cached]

        internal = Internal()

        try:
            config = await internal.request(
                "store", "get_store",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        handler.set_cache(key, config)
        return config

    @promise
    async def new_order(self, store, item, currency, amount, component, env=None, handler=None, *ignored):

        internal = Internal()

        try:
            result = await internal.request(
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

        return result

    @promise
    async def update_order(self, order_id, handler=None, *ignored):

        internal = Internal()

        try:
            result = await internal.request(
                "store", "update_order",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                order_id=order_id)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return result

    @promise
    async def update_orders(self, handler=None, *ignored):

        internal = Internal()

        try:
            result = await internal.request(
                "store", "update_orders",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"])
        except InternalError as e:
            raise APIError(e.code, e.body)

        return result


# noinspection PyUnusedLocal
class ProfileAPI(object):

    @promise
    async def get(self, path="", handler=None, *ignored):

        if not isinstance(path, str):
            raise APIError(400, "Path should be a string")

        internal = Internal()

        try:
            profile = await internal.request(
                "profile", "get_my_profile",
                timeout=API_TIMEOUT,
                gamespace_id=handler.env["gamespace"],
                account_id=handler.env["account"],
                path=path)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return profile

    @promise
    async def update(self, profile=None, path="", merge=True, handler=None, *ignored):

        if not isinstance(path, str):
            raise APIError(400, "Path should be a string")

        key = "profile:" + str(path)
        if not profile:
            profile = {}

        internal = Internal()

        try:
            profile = await internal.request(
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
        return profile

    @promise
    async def query(self, query, limit=1000, handler=None, *ignored):

        if not validate_value(query, "json_dict"):
            raise APIError(400, "Query should be a JSON object")

        internal = Internal()

        try:
            results = await internal.request(
                "profile", "query_profiles",
                timeout=API_TIMEOUT,
                gamespace_id=handler.env["gamespace"],
                query=query,
                limit=limit)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return results


# noinspection PyUnusedLocal
class SocialAPI(object):

    @promise
    async def acquire_name(self, kind, name, handler=None, *ignored):
        internal = Internal()

        try:
            profile = await internal.request(
                "social", "acquire_name",
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                kind=kind,
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return profile

    @promise
    async def check_name(self, kind, name, handler=None, *ignored):
        internal = Internal()

        try:
            account_id = await internal.request(
                "social", "check_name",
                gamespace=handler.env["gamespace"],
                kind=kind,
                name=name)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return account_id

    @promise
    async def release_name(self, kind, handler=None, *ignored):
        internal = Internal()

        try:
            released = await internal.request(
                "social", "release_name",
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                kind=kind)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return released

    @promise
    async def update_profile(self, group_id, profile=None, path=None, merge=True, handler=None, *ignored):
        if path and not isinstance(path, (list, tuple)):
            raise APIError(400, "Path should be a list/tuple")

        internal = Internal()

        try:
            profile = await internal.request(
                "social", "update_group_profile",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                group_id=group_id,
                profile=profile,
                path=path,
                merge=merge)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return profile

    @promise
    async def update_group_profiles(self, group_profiles, path=None, merge=True, synced=False, handler=None, *ignored):
        if not isinstance(group_profiles, dict):
            raise APIError(400, "Group profiles should be a dict")

        if path and not isinstance(path, (list, tuple)):
            raise APIError(400, "Path should be a list/tuple")

        internal = Internal()

        try:
            profile = await internal.request(
                "social", "update_group_profiles",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                group_profiles=group_profiles,
                path=path or [],
                merge=merge,
                synced=synced)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return profile


# noinspection PyUnusedLocal
class MessageAPI(object):

    @promise
    async def send_batch(self, sender, messages, authoritative=True, handler=None, *ignored):

        internal = Internal()

        try:
            await internal.request(
                "message", "send_batch",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                sender=sender,
                messages=messages,
                authoritative=authoritative)
        except InternalError as e:
            raise APIError(e.code, e.body)
        return "OK"


# noinspection PyUnusedLocal
class PromoAPI(object):

    @promise
    async def use_code(self, key, handler=None, *ignored):

        internal = Internal()

        try:
            result = await internal.request(
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

        return result


class EventAPI(object):
    @promise
    async def update_event_profile(self, event_id, profile, path=None, merge=True, handler=None):
        internal = Internal()

        try:
            events = await internal.request(
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

        return events

    @promise
    async def list(self, extra_start_time=0, extra_end_time=0, handler=None):
        internal = Internal()

        try:
            events = await internal.request(
                "event", "get_list",
                timeout=API_TIMEOUT,
                gamespace=handler.env["gamespace"],
                account=handler.env["account"],
                extra_start_time=extra_start_time,
                extra_end_time=extra_end_time)
        except InternalError as e:
            raise APIError(e.code, e.body)

        return events


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

    # define them as readonly
    for name, callback in expose_objects.items():
        context.Object.defineProperty(
            context.glob, name, {'value': callback, 'writable': False})


from tornado.gen import coroutine, Return, with_timeout
from tornado.ioloop import IOLoop

# noinspection PyUnresolvedReferences
from v8py import JSFunction, new, JSPromise, JSException, current_context, JavaScriptTerminated

import ujson
import logging
import traceback


class JavascriptCallHandler(object):
    def __init__(self, cache, env, debug=None, promise_type=None):
        self.cache = cache
        self.env = env
        self.log = JavascriptCallHandler._default_log
        self.debug = debug
        self.promise_type = promise_type

    @staticmethod
    def _default_log(message):
        logging.info(message)

    def get_cache(self, key):
        return self.cache.get(key) if self.cache is not None else None

    def set_cache(self, key, value):
        if self.cache is not None:
            self.cache[key] = value


class APIError(Exception):
    def __init__(self, _code, _message):
        self._code = _code
        self._message = _message
        self.args = [_code, _message]

    @property
    def code(self):
        return self._code

    @property
    def message(self):
        return self._message

    def __str__(self):
        return str(self.code) + ": " + str(self.message)


class PromiseContext(object):
    current = None


class CompletedDeferred(object):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def done(self, func):
        if self.code is True:
            func(True)
        return self

    def fail(self, func):
        if self.code is not True:
            func(self.code, self.message)
        return self


class DeferredAPI(object):
    def __init__(self, api, context, worker):
        super(DeferredAPI, self).__init__()

        self._context = context
        self._worker = worker
        self.api = api

    # noinspection PyProtectedMember
    def _exception(self, exc):
        self.api._exception(exc)


class APIUserError(APIError):
    def __init__(self, code, message):
        super(APIUserError, self).__init__(code, message)


def promise(method):
    """
    This complex decorator allows to wrap coroutine to be used in async/await

    Use it instead of @coroutine to call a method asynchronously from JS:

    @promise
    def sum(a, b):
        yield sleep(1)
        raise Return(a + b)

    When called from JS, a Primise object is returned:

    async function test()
    {
        var result = await sum(5, 10);
    }

    """
    def wrapper(*args, **kwargs):

        # pull a handler from PromiseContext. every javascript call has to set one
        handler = PromiseContext.current

        def promise_callback(resolve, reject):

            def callback(f):
                # once the future done, reset the handler back to ours
                PromiseContext.current = handler

                exception = f.exception()
                if exception:
                    if isinstance(exception, BaseException):
                        reject(exception)
                    else:
                        if hasattr(exception, "stack"):
                            reject(APIError(500, str(exception.stack)))
                        else:
                            reject(APIError(500, str(exception)))

                try:
                    res = f.result()
                except BaseException as exc:
                    reject(exc)
                else:
                    resolve(res)

            try:
                # noinspection PyProtectedMember
                future = coroutine(method)(*args, handler=handler)
            except BaseException as exc:
                reject(exc)
            else:
                IOLoop.current().add_future(future, callback)

        # return a new Promise
        return new(handler.promise_type, promise_callback)
    return wrapper


from tornado.gen import coroutine, Return, with_timeout
from tornado.ioloop import IOLoop

# noinspection PyUnresolvedReferences
from v8py import JSFunction, JSException, current_context, JavaScriptTerminated

import ujson
import logging


class JavascriptCallHandler(object):
    def __init__(self, future, cache, env, debug=None):
        self._future = future
        self.cache = cache
        self.env = env
        self.log = JavascriptCallHandler._default_log
        self.debug = debug

    @staticmethod
    def _default_log(message):
        logging.info(message)

    def _exception(self, exc):
        self._future.set_exception(exc)

    def get_cache(self, key):
        return self.cache.get(key) if self.cache else None

    def set_cache(self, key, value):
        if self.cache:
            self.cache[key] = value

    def res(self, result=None):
        self._future.set_result(result)


class APIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class DeferredContext(object):
    current = None


class Deferred(object):
    def __init__(self):
        self.on_resolve = None
        self.on_reject = None

        self._done = False
        self._success = None
        self._data = None

        self._handler = DeferredContext.current

        if not self._handler:
            raise APIError(500, "Current called is not defined")

    # noinspection PyProtectedMember
    def __call_fn__(self, fn, args):
        DeferredContext.current = self._handler

        try:
            if isinstance(fn, JSFunction):
                fn(*args, timeout=1.0)
            else:
                fn(*args)
        except JavaScriptTerminated:
            exc = APIError(408, "Evaluation process timeout: function shouldn't be blocking and "
                                "should rely on async methods instead.")
            self._handler._exception(exc)
        except JSException as e:
            if isinstance(e.value, APIUserError):
                self._handler._exception(e.value)
            else:
                self._handler._exception(e)
        except Exception as e:
            self._handler._exception(e)

    def done(self, func):
        if self._done:
            # in case deferred is already completed before callback was set
            if self._success:
                self.__call_fn__(func, self._data)
            return self

        self.on_resolve = func
        return self

    def fail(self, func):
        if self._done:
            # in case deferred is already completed before callback was set
            if not self._success:
                self.__call_fn__(func, self._data)
            return self

        self.on_reject = func
        return self

    def resolve(self, *args):
        if self._done:
            return

        self._done = True
        self._success = True
        self._data = args

        if self.on_resolve:
            self.__call_fn__(self.on_resolve, args)

    def reject(self, *args):
        if self._done:
            return

        self._done = True
        self._success = False
        self._data = args

        if self.on_reject:
            self.__call_fn__(self.on_reject, args)


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
        self.code = code
        self.message = message
        self.args = [code, message]


def deferred(method):
    """
    This complex decorator allows to wrap coroutine-like methods for JavaScript usage.

    Use it instead of @coroutine to call a method asynchronously from JS:

    @deferred
    def sum(a, b):
        yield sleep(1)
        raise Return(a + b)

    When called from JS, a Deferred object is returned (like in jQuery):

    var d = sum(5, 10);
    d.done(function(result)
    {
        // result is 15 asynchronously
    });
    d.fail(function(code, error)
    {
        // failed
    });

    And in more sophisticated form:

    sum(5, 10).done(function(result)
    {
        // success
    }).fail(function(code, error)
    {
        // failed
    });

    """
    def wrapper(*args, **kwargs):
        d = Deferred()

        def callback(f):
            exc = f.exception()
            if exc:
                d.reject(*exc.args)
            else:
                if f.result() is None:
                    d.resolve()
                else:
                    d.resolve(*f.result())

        try:
            # noinspection PyProtectedMember
            future = coroutine(method)(d._handler, *args)
        except BaseException as exc:
            d.reject(*exc.args)
        else:
            IOLoop.current().add_future(future, callback)

        return d
    return wrapper

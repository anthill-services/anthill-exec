
from tornado.ioloop import IOLoop
from tornado.gen import Future

# noinspection PyUnresolvedReferences
from v8py import JSFunction, new, JSPromise, JSException, current_context, JavaScriptTerminated

import weakref
import logging
import traceback
import asyncio

from anthill.common.options import options
from anthill.common.internal import InternalError


class JavascriptCallHandler(object):
    def __init__(self, cache, env, context, debug=None, promise_type=None):
        self.cache = cache
        self.context = context
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


class JavascriptExecutionError(Exception):
    def __init__(self, code, message, stack=None):
        self.code = code
        self.message = message
        self.traceback = stack or (traceback.format_exc() if options.debug else None)

    def __str__(self):
        return str(self.code) + ": " + str(self.message)


def process_error(e):
    if isinstance(e, JSException):
        value = e.value
        if hasattr(value, "code"):
            return JavascriptExecutionError(value.code, value.message)
        if hasattr(e, "stack"):
            return JavascriptExecutionError(500, str(e), stack=str(e.stack))
        return JavascriptExecutionError(500, str(e))

    if isinstance(e, APIError):
        return JavascriptExecutionError(e.code, e.message, stack=str(e.stack) if hasattr(e, "stack") else None)

    if isinstance(e, InternalError):
        return JavascriptExecutionError(
            e.code, "Internal error: " + e.body)

    if isinstance(e, JavaScriptTerminated):
        return JavascriptExecutionError(
            408, "Evaluation process timeout: function shouldn't be "
                 "blocking and should rely on async methods instead.")

    code = e.code if hasattr(e, "code") else 500
    stack = e.stack if hasattr(e, "stack") else None
    message = e.message if hasattr(e, "message") else str(e)

    return JavascriptExecutionError(code, message, stack=stack)


class JSFuture(Future):
    def set_exception(self, exception):
        super(JSFuture, self).set_exception(process_error(exception))


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


def promise_completion(f):
    handler = f.bound.handler()

    if handler is None:
        return

        # once the future done, set the handler to ours
    PromiseContext.current = handler

    exception = f.exception()
    if exception:
        exception.stack = "".join(traceback.format_tb(f.exc_info()[2]))
        f.bound_reject(exception)
    else:
        f.bound_resolve(f.result())

    # reset it back
    PromiseContext.current = None

    del f.bound
    del f.bound_reject
    del f.bound_resolve
    del f


def promise_callback(bound, resolve, reject):

    handler = bound.handler()

    if handler is None:
        return

    try:
        # noinspection PyProtectedMember
        coroutine_object = bound.method(*bound.args, handler=handler)
    except BaseException as exc:
        exc.stack = traceback.format_exc()
        reject(exc)
    else:
        task = asyncio.ensure_future(coroutine_object)
        task.bound = bound
        task.bound_resolve = resolve
        task.bound_reject = reject
        task.add_done_callback(promise_completion)


class BoundPromise(object):
    def __init__(self, handler, method, args):
        self.handler = weakref.ref(handler)
        self.method = method
        self.args = args


def promise(method):
    """
    This complex decorator allows to wrap coroutine to be used in async/await

    Use it instead of @coroutine to call a method asynchronously from JS:

    @promise
    async def sum(a, b):
        await sleep(1)
        return a + b

    When called from JS, a Primise object is returned:

    async function test()
    {
        var result = await sum(5, 10);
    }

    """
    def wrapper(*args, **kwargs):
        # pull a handler from PromiseContext. every javascript call has to set one
        handler = PromiseContext.current
        context = handler.context

        return new(handler.promise_type, context.bind(promise_callback, BoundPromise(handler, method, args)))
    return wrapper

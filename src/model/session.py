
import datetime

from tornado.gen import coroutine, Return, with_timeout, Future, TimeoutError
# noinspection PyUnresolvedReferences
from v8py import JSException, Context, new, JavaScriptTerminated

from common.access import InternalError
from common.validate import validate
from util import APIError, APIUserError, DeferredContext, JavascriptCallHandler
from expiringdict import ExpiringDict


class JavascriptSessionError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class JavascriptSession(object):

    CALL_BLACKLIST = ["release", "init"]

    def __init__(self, build, instance, env, log, debug):
        self.build = build
        self.instance = instance
        self.cache = ExpiringDict(10, 60)
        self.env = env

        self.log = log
        self.debug = debug

    def init(self):
        return self.call_internal_method("init", {})

    @coroutine
    def call_internal_method(self, method_name, args, call_timeout=10):

        method = getattr(self.instance, method_name, None)

        if not method:
            return

        future = Future()
        handler = JavascriptCallHandler(future, self.cache, self.env, debug=self.debug)
        if self.log:
            handler.log = self.log
        DeferredContext.current = handler

        try:
            result = method(args)
        except JSException as e:
            raise APIError(500, e.message)
        except JavaScriptTerminated:
            raise APIError(408, "Evaluation process timeout: function shouldn't be blocking and "
                                "should rely on async methods instead.")
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        else:
            if result:
                raise Return(result)
            if future.done():
                raise Return(future.result())

        try:
            result = yield with_timeout(datetime.timedelta(seconds=call_timeout), future)
        except TimeoutError:
            raise APIError(408, "Total function '{0}' call timeout ({1})".format(
                method_name, call_timeout))
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        else:
            raise Return(result)

    @coroutine
    @validate(method_name="str_name", args="json_dict")
    def call(self, method_name, args, call_timeout=10):

        if method_name.startswith("_"):
            raise JavascriptSessionError(404, "No such method: " + str(method_name))

        if method_name in JavascriptSession.CALL_BLACKLIST:
            raise JavascriptSessionError(404, "No such method: " + str(method_name))

        if not hasattr(self.instance, method_name):
            raise JavascriptSessionError(404, "No such method: " + str(method_name))

        method = getattr(self.instance, method_name)

        future = Future()
        handler = JavascriptCallHandler(future, self.cache, self.env, debug=self.debug)
        if self.log:
            handler.log = self.log
        DeferredContext.current = handler

        try:
            result = method(args, args)
        except JSException as e:
            raise APIError(500, e.message)
        except JavaScriptTerminated:
            raise APIError(408, "Evaluation process timeout: function shouldn't be blocking and "
                                "should rely on async methods instead.")
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        else:
            if result:
                raise Return(result)
            if future.done():
                raise Return(future.result())

        try:
            result = yield with_timeout(datetime.timedelta(seconds=call_timeout), future)
        except TimeoutError:
            raise APIError(408, "Total function '{0}' call timeout ({1})".format(
                method_name, call_timeout))
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        else:
            raise Return(result)

    @coroutine
    @validate(value="str")
    def eval(self, value):

        future = Future()
        handler = JavascriptCallHandler(future, self.cache, self.env)
        DeferredContext.current = handler

        # this allows eval to access session instance variables directly
        # used for debugging purposes only so that's okay
        hack = "with (instance) {\n" + str(value) + "\n}"

        try:
            result = self.build.context.eval(str(hack))
        except JSException as e:
            raise APIError(500, e.message)
        except JavaScriptTerminated:
            raise APIError(408, "Evaluation process timeout: function shouldn't be blocking and "
                                "should rely on async methods instead.")
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)

        raise Return(result)

    @coroutine
    def release(self, code=1006, reason="Closed normally"):
        yield self.call_internal_method("release", {
            "code": code,
            "reason": reason
        })
        if self.build:
            yield self.build.session_released(self)
            self.debug = None
        self.instance = None

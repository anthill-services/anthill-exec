

from tornado.gen import coroutine, Return, with_timeout, Future, TimeoutError
# noinspection PyUnresolvedReferences
from v8py import JSException, JSPromise, Context, new, JavaScriptTerminated

from common.access import InternalError
from common.validate import validate
from util import APIError, PromiseContext, JavascriptCallHandler, JavascriptExecutionError, process_error
from expiringdict import ExpiringDict

import datetime
import sys
import logging


class JavascriptSessionError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class JavascriptSession(object):

    CALL_BLACKLIST = ["release"]

    def __init__(self, build, instance, env, log, debug, promise_type):
        self.build = build
        self.instance = instance
        self.cache = ExpiringDict(10, 60)
        self.env = env

        self.log = log
        self.debug = debug
        self.promise_type = promise_type

    @coroutine
    def call_internal_method(self, method_name, args, call_timeout=10):

        method = getattr(self.instance, method_name, None)

        if not method:
            return

        handler = JavascriptCallHandler(self.cache, self.env, debug=self.debug, promise_type=self.promise_type)
        if self.log:
            handler.log = self.log
        PromiseContext.current = handler

        try:
            result = method(args)
        except JSException as e:
            value = e.value
            if hasattr(value, "code"):
                raise JavascriptExecutionError(value.code, value.message)
            if hasattr(e, "stack"):
                raise JavascriptExecutionError(500, str(e), stack=str(e.stack))
            raise JavascriptExecutionError(500, str(e))
        except APIError as e:
            raise JavascriptExecutionError(e.code, e.message)
        except InternalError as e:
            raise JavascriptExecutionError(
                e.code, "Internal error: " + e.body)
        except JavaScriptTerminated:
            raise JavascriptExecutionError(
                408, "Evaluation process timeout: function shouldn't be "
                     "blocking and should rely on async methods instead.")
        except Exception as e:
            raise JavascriptExecutionError(500, str(e))

        # if the function is defined as 'async', a Promise will be returned
        if isinstance(result, JSPromise):
            future = Future()

            def error(e):
                future.set_exception(process_error(e))

            # connect a promise right into the future
            try:
                result.then(future.set_result, error)
            except Exception as e:
                pass

            if future.done():
                raise Return(future.result())
        else:
            # immediate result
            raise Return(result)

        try:
            result = yield with_timeout(datetime.timedelta(seconds=call_timeout), future)
        except TimeoutError:
            raise APIError(408, "Total function '{0}' call timeout ({1})".format(
                method_name, call_timeout))
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

        handler = JavascriptCallHandler(self.cache, self.env, debug=self.debug, promise_type=self.promise_type)
        if self.log:
            handler.log = self.log
        PromiseContext.current = handler

        try:
            result = method(args, args)
        except JSException as e:
            value = e.value
            if hasattr(value, "code"):
                raise JavascriptExecutionError(value.code, value.message)
            if hasattr(e, "stack"):
                raise JavascriptExecutionError(500, str(e), stack=str(e.stack))
            raise JavascriptExecutionError(500, str(e))
        except APIError as e:
            raise JavascriptExecutionError(e.code, e.message)
        except InternalError as e:
            raise JavascriptExecutionError(
                e.code, "Internal error: " + e.body)
        except JavaScriptTerminated:
            raise JavascriptExecutionError(
                408, "Evaluation process timeout: function shouldn't be "
                     "blocking and should rely on async methods instead.")
        except Exception as e:
            raise JavascriptExecutionError(500, str(e))

        # if the function is defined as 'async', a Promise will be returned
        if isinstance(result, JSPromise):
            future = Future()

            def error(e):
                e = process_error(e)
                future.set_exception(e)

            # connect a promise right into the future
            try:
                result.then(future.set_result, error)
            except Exception as e:
                pass

            if future.done():
                raise Return(future.result())
        else:
            # immediate result
            raise Return(result)

        try:
            result = yield with_timeout(datetime.timedelta(seconds=call_timeout), future)
        except TimeoutError:
            raise APIError(408, "Total function '{0}' call timeout ({1})".format(
                method_name, call_timeout))
        else:
            raise Return(result)

    @coroutine
    @validate(value="str")
    def eval(self, value):

        handler = JavascriptCallHandler(self.cache, self.env)
        PromiseContext.current = handler

        try:
            result = self.build.context.eval(str(value))
        except JSException as e:
            raise APIError(500, e.message)
        except JavaScriptTerminated:
            raise APIError(408, "Evaluation process timeout: function shouldn't be blocking and "
                                "should rely on async methods instead.")
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        except APIError:
            raise
        except Exception as e:
            raise APIError(500, e)

        raise Return(result)

    @coroutine
    def release(self, code=1006, reason="Closed normally"):
        yield self.call_internal_method("released", {
            "code": code,
            "reason": reason
        })
        if self.build:
            yield self.build.session_released(self)
            self.debug = None
        self.instance = None

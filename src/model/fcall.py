from tornado.gen import coroutine, Return, Future, with_timeout, TimeoutError
from tornado.ioloop import IOLoop

from common.model import Model
from common.access import InternalError
from expiringdict import ExpiringDict
import datetime

from concurrent.futures import ProcessPoolExecutor
from common import ElapsedTime, SyncTimeout
from common.options import options

import logging
import ujson

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

try:
    from PyV8 import JSClass, JSContext, JSEngine, JSError, JSLocker, JSArray, convert
except ImportError:
    # noinspection PyUnresolvedReferences
    from pyv8.PyV8 import JSClass, JSContext, JSEngine, JSError, JSLocker, JSArray, convert


class APIError(Exception):
    def __init__(self, code=0, message=None):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class Deferred(object):
    def __init__(self, obj):
        self.on_resolve = None
        self.on_reject = None
        self.obj = obj

    def done(self, func):
        self.on_resolve = func
        return self

    def fail(self, func):
        self.on_reject = func
        return self

    def resolve(self, *args):
        with self.obj:
            if self.obj._active and self.on_resolve:
                self.on_resolve(*args)

    def reject(self, *args):
        with self.obj:
            if self.obj._active and self.on_reject:
                self.on_reject(*args)


def deferred(f):
    def wrapped(self, *args, **kwargs):
        d = Deferred(self)

        # noinspection PyShadowingNames
        def done(f):
            exc = f.exception()
            try:
                with SyncTimeout(1):
                    if exc:
                        d.reject(exc)
                    else:
                        d.resolve(f.result())
            except SyncTimeout.TimeoutError:
                self.exception(FunctionCallError(
                    "Function call process timeout: function shouldn't be blocking and should rely "
                    "on async methods instead."))
            except JSError as e:
                if APIUserError.user(e):
                    code, message = APIUserError.parse(e)
                    exc = APIError(code, message)
                else:
                    exc = FunctionCallError(str(e) + "\n" + e.stackTrace)

                self.exception(exc)

        future = coroutine(f)(self, *args, **kwargs)
        IOLoop.current().add_future(future, done)

        return d

    return wrapped


class APIUserError(object):
    def __init__(self, code, message):
        self.message = ujson.dumps([code, message])
        self.name = "APIUserError"

    @staticmethod
    def user(e):
        return hasattr(e, "name") and e.name == "APIUserError"

    @staticmethod
    def parse(e):
        message = e.message
        try:
            data = ujson.loads(message)
        except Exception as e:
            return 500, e.message
        else:
            if not isinstance(data, list):
                return 500, "Error is not a list"

            return data[0], data[1]


class APIBase(object):
    def __init__(self, debug, callback):
        object.__setattr__(self, "_", False)

        with self:
            self._debug = debug
            self._callback = callback
            self._active = True

    def __enter__(self):
        object.__setattr__(self, "_", True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        object.__setattr__(self, "_", False)

    def __getattribute__(self, name):
        if object.__getattribute__(self, "_"):
            return object.__getattribute__(self, name)

        if name.startswith("_"):
            return None

        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        if not object.__getattribute__(self, "_"):
            if name.startswith("_"):
                return None

        return object.__setattr__(self, name, value)

    def log(self, message, *ignored):
        with self:
            d = self._debug
            if d:
                d.log(message)

    def toDict(self):
        return {}

    def exception(self, exc):
        with self:
            cb = self._callback
            if cb and not cb.done():
                self._active = False
                cb.set_exception(exc)

    def res(self, result):
        with self:
            cb = self._callback
            if cb and not cb.done():
                self._active = False
                cb.set_result(convert(result))


class FunctionCallError(Exception):
    def __init__(self, message=None):
        self.message = message

    def __str__(self):
        return self.message


class NoSuchMethodError(FunctionCallError):
    def __init__(self, method):
        super(NoSuchMethodError, self).__init__("No {0}() function found.".format(method))


class CompiledFunction(object):
    def __init__(self, name, source, precompiled):
        self.name = name
        self.source = source
        self.precompiled = precompiled


def __precompile__(functions):
    with JSEngine() as engine:

        result = {}

        for name, source in functions.iteritems():
            try:
                result[name] = bytearray(engine.precompile(source))
            except JSError as e:
                raise FunctionCallError(e)
            except Exception as e:
                raise FunctionCallError(str(e))

        return result


class JSAPIEnvironment(object):
    def __init__(self, env):
        self.env = env

    # noinspection PyMethodMayBeStatic
    def error(self, *args):
        if len(args) >= 2:
            exception = APIUserError(args[0], args[1])
        elif len(args) >= 1 and isinstance(args[0], Exception):
            exception = APIUserError(500, str(args[0]))
        else:
            exception = APIUserError(500, "Internal Script Error")

        return exception


class JSAPIContext(JSContext):
    def __init__(self, env):
        super(JSAPIContext, self).__init__(JSAPIEnvironment(env))
        self.env = env

    def __exit__(self, exc_type, exc_value, traceback):
        super(JSAPIContext, self).__exit__(exc_type, exc_value, traceback)


class CallSession(object):
    def __init__(self, model, function_name, functions, debug, **env):
        self.context = JSAPIContext(env)
        self.debug = debug
        self.gamespace = env["gamespace"]
        self.account_id = env["account"]
        self.function_name = function_name
        self.engine = JSEngine()
        self.functions = functions
        self.model = model
        self.name = ""

    @coroutine
    def init(self):
        self.context.enter()

        for fn in self.functions:
            try:
                with SyncTimeout(5):
                    self.engine.compile(fn.source, precompiled=fn.precompiled).run()
            except JSError as e:
                raise FunctionCallError("Failed to compile '{0}': ".format(fn.name) + str(e))
            except SyncTimeout.TimeoutError:
                raise FunctionCallError(
                    "Function compile timeout: function shouldn't be blocking and should rely "
                    "on async methods instead.")

            except Exception as e:
                raise FunctionCallError(str(e))

        self.name = "gamespace {0} / user @{1} / function '{2}'".format(
            self.gamespace, self.account_id, self.function_name)

        logging.info("Session started: " + self.name)

    @coroutine
    def call(self, method_name, arguments):
        result = yield self.model.__run__(self.context, method_name, arguments, debug=self.debug)
        raise Return(result)

    def eval(self, text):
        return self.model.__eval__(self.context, str(text))

    @coroutine
    def release(self, code=0, reason=""):

        try:
            yield self.model.__run__(self.context, "released", {"code": code, "reason": reason or ""})
        except NoSuchMethodError:
            pass
        except Exception as e:
            logging.info("Error while releasing: {0}".format(str(e)))

        del self.engine
        self.context.leave()

        logging.info("Session released: @{0}".format(self.name))


class FunctionsCallModel(Model):
    def __init__(self, functions, cache):

        self.call_timeout = options.js_call_timeout
        self.compile_pool = ProcessPoolExecutor(max_workers=(options.js_compile_workers or None))

        self.cache = cache
        self.functions = functions
        self.saved_code = ExpiringDict(max_len=64, max_age_seconds=60)

    @coroutine
    def prepare(self, gamespace_id, application_name, function_name, cache=True, debug=None):
        key = str(gamespace_id) + ":" + str(function_name)

        if cache:
            result = self.saved_code.get(key, None)
        else:
            result = None

        if not result:
            logging.info("Compiling function '{0}'...".format(function_name))

            if debug:
                debug.log("Compiling function '{0}'...".format(function_name))

            # gather all functions with dependent functions (a dict name: source)
            functions = (yield self.functions.get_function_with_dependencies(
                gamespace_id,
                application_name,
                function_name))

            # compile all functions in parallel
            precompiled_functions = yield self.compile_pool.submit(__precompile__, functions)

            # collect them together
            result = [
                CompiledFunction(name, functions[name], precompiled)
                for name, precompiled in precompiled_functions.iteritems()
                ]

            self.saved_code[key] = result

        raise Return(result)

    def stopped(self):
        self.compile_pool.shutdown()

    @coroutine
    def __run_context__(self, functions, method_name, arguments, debug=None, **env):
        with JSAPIContext(env) as context:
            with JSEngine() as engine:
                for fn in functions:
                    try:
                        engine.compile(fn.source, name=str(fn.name), line=-1, col=-1, precompiled=fn.precompiled).run()
                    except JSError as e:
                        raise FunctionCallError("Failed to compile '{0}': ".format(fn.name) + str(e))
                    except Exception as e:
                        raise FunctionCallError(str(e))

                result = yield self.__run__(context, method_name, arguments, debug=debug)
                raise Return(result)

    # noinspection PyMethodMayBeStatic
    def __eval__(self, context, text):
        try:
            with SyncTimeout(1):
                return convert(context.eval(text))
        except JSError as e:
            if APIUserError.user(e):
                code, message = APIUserError.parse(e)
                raise APIError(code, message)

            raise FunctionCallError(str(e) + "\n" + e.stackTrace)
        except SyncTimeout.TimeoutError:
            raise FunctionCallError("Eval timeout.")
        except Exception as e:
            raise FunctionCallError(str(e))

    @coroutine
    def __run__(self, context, method, arguments, debug=None):
        from api import API

        if not isinstance(method, (str, unicode)):
            raise FunctionCallError("Method is not a string")

        if method.startswith("_"):
            raise FunctionCallError("Cannot call such method")

        if not hasattr(context.locals, method):
            raise NoSuchMethodError(method)

        method_function = getattr(context.locals, method, None)

        if not method_function:
            raise NoSuchMethodError(method)

        future = Future()

        run_api = API(context.env, debug=debug, callback=future)

        try:
            with SyncTimeout(1):
                method_function.apply(method_function, [arguments, run_api])
        except JSError as e:
            if APIUserError.user(e):
                code, message = APIUserError.parse(e)
                raise APIError(code, message)

            raise FunctionCallError(str(e) + "\n" + e.stackTrace)
        except SyncTimeout.TimeoutError:
            raise FunctionCallError("Function call process timeout: function shouldn't be blocking and should rely "
                                    "on async methods instead.")
        except Exception as e:
            raise FunctionCallError(str(e))

        try:
            result = yield with_timeout(datetime.timedelta(seconds=self.call_timeout), future)
        except TimeoutError:
            raise FunctionCallError("Function call timeout")
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        else:
            raise Return(result)

    @coroutine
    def session(self, application_name, function_name, cache=True, debug=None, **env):

        t = ElapsedTime("Session {0}/{1} creation".format(application_name, function_name))
        fns = yield self.prepare(env["gamespace"], application_name, function_name, cache, debug=debug)
        session = CallSession(self, function_name, fns, debug=debug, **env)
        yield session.init()
        logging.info(t.done())

        raise Return(session)

    @coroutine
    def call(self, application_name, function_name, arguments, method_name="main", cache=True, debug=None, **env):

        if not isinstance(arguments, (dict, list)):
            raise FunctionCallError("arguments expected to be a list or dict")

        t = ElapsedTime("Function execution")
        fns = yield self.prepare(env["gamespace"], application_name, function_name, cache)
        result = yield self.__run_context__(fns, method_name, arguments, debug, **env)
        logging.info(t.done())

        raise Return(result)

    @coroutine
    def call_fn(self, functions, arguments, method_name="main", **env):

        if not isinstance(arguments, (dict, list)):
            raise FunctionCallError("arguments expected to be a list or dict")

        result = yield self.__run_context__(functions, method_name, arguments, None, **env)

        raise Return(result)

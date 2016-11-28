
from tornado.gen import coroutine, Return, Future, with_timeout, TimeoutError
from tornado.ioloop import IOLoop, stack_context

from common.model import Model
from common.access import InternalError
from expiringdict import ExpiringDict
from functools import wraps, partial
import datetime

from concurrent.futures import ProcessPoolExecutor
from common import ElapsedTime
from common.options import options
import logging

# pip install -e git://github.com/brokenseal/PyV8-OS-X#egg=pyv8

try:
    from PyV8 import JSClass, JSContext, JSEngine, JSError, JSLocker, convert
except ImportError:
    from pyv8.PyV8 import JSClass, JSContext, JSEngine, JSError, JSLocker, convert


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
        if self.obj.active and self.on_resolve:
            self.on_resolve(*args)

    def reject(self, *args):
        if self.obj.active and self.on_reject:
            self.on_reject(*args)


def deferred(f):

    def wrapped(self, *args):
        d = Deferred(self)

        def done(f):
            exc = f.exception()
            try:
                if exc:
                    d.reject(exc)
                else:
                    d.resolve(f.result())
            except JSError as e:
                self.future.set_exception(FunctionCallError(str(e)))

        future = f(self, *args)
        IOLoop.current().add_future(future, done)

        return d

    return wrapped


class Response(object):
    def __init__(self):
        self.future = None

    def set_response(self, future):
        self.future = future

    def error(self, *args):
        if len(args) >= 2:
            exception = APIError(args[0], args[1])
        elif len(args) >= 1 and isinstance(args[0], Exception):
            exception = args[0]
        else:
            exception = APIError(500, "Internal Script Error")

        if self.future:
            self.future.set_exception(exception)

    def res(self, result):
        if self.future:
            self.future.set_result(convert(result))


class APIBase(object):
    def __init__(self, debug):
        self.response = Response()
        self.active = True
        self.debug = debug

    def release(self):
        self.active = False

    def log(self, data, *ignored):

        logging.info(data)

        if self.debug:
            self.debug.log(data)

    def error(self, *args):
        self.response.error(*args)

    def res(self, result):
        self.response.res(result)


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


class Debug(object):
    def __init__(self):
        self.collected_log = ""

    def log(self, data):
        self.collected_log += data + "\n"


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


class JSAPIContext(JSContext):
    def __init__(self, env, debug):
        from api import API

        self.obj = API(env, IOLoop.current(), debug)
        super(JSAPIContext, self).__init__(self.obj)

    def set_response(self, future):
        self.obj.response.set_response(future)

    def __exit__(self, exc_type, exc_value, traceback):
        self.obj.release()
        super(JSAPIContext, self).__exit__(exc_type, exc_value, traceback)


class CallSession(object):
    def __init__(self, model, function_name, functions, **env):
        self.context = JSAPIContext(env, False)
        self.gamespace = env["gamespace"]
        self.account_id = env["account"]
        self.function_name = function_name
        self.engine = JSEngine()
        self.functions = functions
        self.model = model

    @coroutine
    def init(self):
        self.context.enter()

        for fn in self.functions:
            try:
                self.engine.compile(fn.source, precompiled=fn.precompiled).run()
            except JSError as e:
                raise FunctionCallError("Failed to compile '{0}': ".format(fn.name) + str(e))
            except Exception as e:
                raise FunctionCallError(str(e))

        logging.info("Session started: @{0} user {1} fn {2}".format(
            self.gamespace, self.account_id, self.function_name
        ))

    @coroutine
    def call(self, method_name, arguments):
        result = yield self.model.__run__(self.context, method_name, arguments)
        raise Return(result)

    @coroutine
    def release(self):
        del self.engine
        self.context.leave()

        logging.info("Session released: @{0} user {1} fn {2}".format(
            self.gamespace, self.account_id, self.function_name
        ))


class FunctionsCallModel(Model):
    def __init__(self, functions, cache):

        self.call_timeout = options.js_call_timeout
        self.compile_pool = ProcessPoolExecutor(max_workers=(options.js_compile_workers or None))

        self.cache = cache
        self.functions = functions
        self.saved_code = ExpiringDict(max_len=64, max_age_seconds=60)

    @coroutine
    def prepare(self, gamespace_id, application_name, function_name, cache=True):
        key = str(gamespace_id) + ":" + str(function_name)

        if cache:
            result = self.saved_code.get(key, None)
        else:
            result = None

        if not result:

            logging.info("Compiling function '{0}'...".format(function_name))

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
    def __run_context__(self, functions, method_name, arguments, debug, **env):
        with JSAPIContext(env, debug) as context:
            with JSEngine() as engine:
                for fn in functions:
                    try:
                        engine.compile(fn.source, precompiled=fn.precompiled).run()
                    except JSError as e:
                        raise FunctionCallError("Failed to compile '{0}': ".format(fn.name) + str(e))
                    except Exception as e:
                        raise FunctionCallError(str(e))

                result = yield self.__run__(context, method_name, arguments)
                raise Return(result)

    @coroutine
    def __run__(self, context, method, arguments):

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
        context.set_response(future)

        try:
            method_function.apply(method_function, [arguments])
        except JSError as e:
            raise FunctionCallError(str(e) + "\n" + e.stackTrace)
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

    def debug(self):
        return Debug()

    @coroutine
    def session(self, application_name, function_name, cache=True, **env):

        t = ElapsedTime("Session {0}/{1} creation".format(application_name, function_name))
        fns = yield self.prepare(env["gamespace"], application_name, function_name, cache)
        session = CallSession(self, function_name, fns, **env)
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

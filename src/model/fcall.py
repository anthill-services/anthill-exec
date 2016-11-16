
from tornado.gen import coroutine, Return, Future, with_timeout, TimeoutError
from tornado.ioloop import IOLoop
from common.model import Model
from common.access import InternalError
from expiringdict import ExpiringDict
from functools import wraps
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
            if exc:
                d.reject(exc)
            else:
                d.resolve(f.result())

        future = f(self, *args)
        IOLoop.current().add_future(future, done)

        return d

    return wrapped


class APIBase(object):
    def __init__(self, future, debug):
        self.future = future
        self.active = True
        self.debug = debug

    def release(self):
        self.active = False

    def log(self, data, *ignored):

        logging.info(data)

        if self.debug:
            self.debug.log(data)

    def error(self, *args):

        if len(args) >= 2:
            exception = APIError(args[0], args[1])
        elif len(args) >= 1 and isinstance(args[0], Exception):
            exception = args[0]
        else:
            exception = APIError(500, "Internal Script Error")

        self.future.set_exception(exception)

    def res(self, result):
        self.future.set_result(convert(result))


class FunctionCallError(Exception):
    def __init__(self, message=None):
        self.message = message

    def __str__(self):
        return self.message


class NoMainMethodError(FunctionCallError):
    def __init__(self):
        super(NoMainMethodError, self).__init__("No main() function found.")


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
    def __init__(self, future, env, debug):
        from api import API

        self.obj = API(future, env, IOLoop.current(), debug)
        super(JSAPIContext, self).__init__(self.obj)

    def __exit__(self, exc_type, exc_value, traceback):
        self.obj.release()
        super(JSAPIContext, self).__exit__(exc_type, exc_value, traceback)


class FunctionsCallModel(Model):
    def __init__(self, functions, cache):

        self.call_timeout = options.js_call_timeout
        self.compile_pool = ProcessPoolExecutor(max_workers=(options.js_compile_workers or None))

        self.cache = cache
        self.functions = functions
        self.saved_code = ExpiringDict(max_len=64, max_age_seconds=60)

    @coroutine
    def prepare(self, gamespace_id, application_name, function_name, cache):
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
    def __run__(self, functions, arguments, debug, **env):

        future = Future()

        with JSAPIContext(future, env, debug) as context:
            with JSEngine() as engine:

                for fn in functions:
                    try:
                        engine.compile(fn.source, precompiled=fn.precompiled).run()
                    except JSError as e:
                        raise FunctionCallError("Failed to compile '{0}': ".format(fn.name) + str(e))
                    except Exception as e:
                        raise FunctionCallError(str(e))

                if not hasattr(context.locals, "main"):
                    raise NoMainMethodError()

                main = context.locals.main

                try:
                    main.apply(main, arguments)
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
    def call(self, application_name, function_name, arguments, cache=True, debug=None, **env):

        if not isinstance(arguments, list):
            raise FunctionCallError("arguments expected to be a list")

        t = ElapsedTime("Function execution")
        fns = yield self.prepare(env["gamespace"], application_name, function_name, cache)
        result = yield self.__run__(fns, arguments, debug, **env)
        logging.info(t.done())

        raise Return(result)

    @coroutine
    def call_fn(self, functions, arguments, **env):

        if not isinstance(arguments, list):
            raise FunctionCallError("arguments expected to be a list")

        result = yield self.__run__(functions, arguments, **env)

        raise Return(result)

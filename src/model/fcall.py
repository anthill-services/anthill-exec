
from tornado.gen import coroutine, Return
from tornado.ioloop import IOLoop
from common.model import Model
from expiringdict import ExpiringDict
from concurrent.futures import ProcessPoolExecutor

from common.options import options
from common import ElapsedTime

import pickle

# pip install -e git://github.com/brokenseal/PyV8-OS-X#egg=pyv8

from pyv8.PyV8 import JSClass, JSContext, JSEngine, JSError, JSLocker


class APIError(Exception):
    def __init__(self, code=0, message=None):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class APIBase(object):
    def __init__(self):
        self.exception = None

    def error(self, code, message):
        exception = APIError(code, message)
        self.exception = exception
        raise exception

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


def __precompile__(functions):
    with JSLocker():
        with JSEngine() as engine:

            result = {}

            for name, source in functions.iteritems():
                try:
                    result[name] = bytes(engine.precompile(source))
                except JSError as e:
                    raise FunctionCallError(e)
                except Exception as e:
                    raise FunctionCallError(str(e))

            return result


def __run__(functions, arguments, **env):
    with JSLocker():
        from api import API

        call_api = API(env)

        with JSContext(call_api) as context:
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
                    result = main.apply(main, arguments)
                except JSError as e:
                    if call_api.exception:
                        raise call_api.exception

                    raise FunctionCallError(str(e) + "\n" + e.stackTrace)
                except Exception as e:
                    raise FunctionCallError(str(e))

                return result


class FunctionsCallModel(Model):
    def __init__(self, functions, cache):

        self.pool = ProcessPoolExecutor(max_workers=options.js_max_workers)

        self.cache = cache
        self.functions = functions
        self.saved_code = ExpiringDict(max_len=64, max_age_seconds=60)

    @coroutine
    def prepare(self, gamespace_id, application_name, function_name):
        key = str(gamespace_id) + ":" + str(function_name)

        result = self.saved_code.get(key, None)

        if not result:

            # gather all functions with dependent functions (a dict name: source)
            functions = (yield self.functions.get_function_with_dependencies(
                gamespace_id,
                application_name,
                function_name))

            # compile all functions in parallel
            precompiled_functions = yield self.pool.submit(__precompile__, functions)

            # collect them together
            result = [
                CompiledFunction(name, functions[name], precompiled)
                for name, precompiled in precompiled_functions.iteritems()
            ]

            self.saved_code[key] = result

        raise Return(result)

    def stopped(self):
        self.pool.shutdown()

    @coroutine
    def call(self, application_name, function_name, arguments, **env):

        if not isinstance(arguments, list):
            raise FunctionCallError("arguments expected to be a list")

        fns = yield self.prepare(env["gamespace"], application_name, function_name)
        result = yield self.pool.submit(__run__, fns, arguments, **env)

        raise Return(result)

    @coroutine
    def call_fn(self, functions, arguments, **env):

        if not isinstance(arguments, list):
            raise FunctionCallError("arguments expected to be a list")

        result = yield self.pool.submit(__run__, functions, arguments, **env)

        raise Return(result)

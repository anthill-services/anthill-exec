
from tornado.gen import coroutine, Return, Future, with_timeout, TimeoutError, sleep
from tornado.ioloop import IOLoop
from tornado.concurrent import return_future

from common.model import Model
from common.access import InternalError
from expiringdict import ExpiringDict

from common import ElapsedTime
from common.options import options

import logging
import ujson
import multiprocessing
import datetime
import Queue

from threading import Thread, Lock

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO


from PyV8 import JSIsolate, JSContext, JSEngine, JSError, JSLocker, JSFunction, convert


FUNCTION_CALL_TIMEOUT = 1000L


class APIError(Exception):
    def __init__(self, code=0, message=None):
        super(APIError, self).__init__(code, message)
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class Deferred(object):
    def __init__(self):
        self.on_resolve = None
        self.on_reject = None

        self._done = False
        self._success = None
        self._data = None

    @staticmethod
    def __call_fn__(fn, args):
        if isinstance(fn, JSFunction):
            try:
                fn.apply(fn, list(args))
            except JSError as e:
                if APIUserError.user(e):
                    code, message = APIUserError.parse(e)
                    raise APIError(code, message)

                raise FunctionCallError("Failed to call '{0}': ".format(fn.name) + str(e))
            except Exception as e:
                raise FunctionCallError(str(e))
        else:
            IOLoop.instance().spawn_callback(fn, *args)

    def done(self, func):
        if self._done:
            # in case deferred is already completed before callback was set
            if self._success:
                Deferred.__call_fn__(func, self._data)
            return self

        self.on_resolve = func
        return self

    def fail(self, func):
        if self._done:
            # in case deferred is already completed before callback was set
            if not self._success:
                Deferred.__call_fn__(func, self._data)
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
            Deferred.__call_fn__(self.on_resolve, args)

    def reject(self, *args):
        if self._done:
            return

        self._done = True
        self._success = False
        self._data = args

        if self.on_reject:
            Deferred.__call_fn__(self.on_reject, args)


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
    def wrapper(self, *args, **ignored):
        d = Deferred()

        def success(result):
            try:
                with self._context:
                    d.resolve(*result)
            except JSError as e:
                if APIUserError.user(e):
                    code, message = APIUserError.parse(e)
                    exc = APIError(code, message)
                else:
                    exc = FunctionCallError(str(e) + "\n" + e.stackTrace)

                self._exception(exc)
            except Exception as e:
                self._exception(e)

        def failure(exc):
            try:
                with self._context:
                    if isinstance(exc, APIError):
                        d.reject(*exc.args)
                    else:
                        d.reject(500, str(exc))
            except JSError as e:
                if APIUserError.user(e):
                    code, message = APIUserError.parse(e)
                    exc = APIError(code, message)
                else:
                    exc = FunctionCallError(str(e) + "\n" + e.stackTrace)

                self._exception(exc)
            except Exception as e:
                self._exception(e)

        ioloop = IOLoop.instance()

        @coroutine
        def call_on_main_thread(*_args):
            # noinspection PyBroadException
            try:
                result = yield coroutine(method)(self, *_args)
            except BaseException as exc:
                submit = self._worker.submit_yield(failure, (exc,))
            else:
                submit = self._worker.submit_yield(success, (result or [],))

            f = yield submit

            try:
                yield with_timeout(
                    timeout=datetime.timedelta(milliseconds=FUNCTION_CALL_TIMEOUT),
                    future=f)
            except TimeoutError:
                self._worker.__terminate__()
                self._exception(APICallTimeoutError(
                    "Evaluation process timeout: function shouldn't be blocking and "
                    "should rely on async methods instead."))

        ioloop.spawn_callback(call_on_main_thread, *map(convert, args))

        return d
    return wrapper


class APIUserError(object):
    def __init__(self, code, message):
        self.args = [code, message]
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
    def __init__(self, context, callback):
        super(APIBase, self).__init__()

        self._context = context
        self._callback = callback
        self._active = True

    # noinspection PyMethodMayBeStatic
    def completed(self, code, message=""):
        return CompletedDeferred(code, message)

    # noinspection PyMethodMayBeStatic
    def toDict(self):
        return {}

    def _exception(self, exc):
        cb = self._callback
        if cb and not cb.done():
            self._active = False
            IOLoop.instance().spawn_callback(cb.set_exception, exc)


class FunctionCallError(Exception):
    def __init__(self, message=None):
        super(FunctionCallError, self).__init__(message)
        self.message = message

    def __str__(self):
        return self.message


class APICallTimeoutError(FunctionCallError):
    def __init__(self, message):
        super(APICallTimeoutError, self).__init__(message)


class NoSuchMethodError(FunctionCallError):
    def __init__(self, method):
        super(NoSuchMethodError, self).__init__("No {0}() function found.".format(method))


class CompiledFunction(object):
    def __init__(self, name, source, precompiled):
        self.name = name
        self.source = source
        self.precompiled = precompiled


class JSAPIEnvironment(object):
    def __init__(self, env, debug=None):
        self.env = env
        self.cache = ExpiringDict(10, 60)
        self._debug = debug

    # noinspection PyMethodMayBeStatic
    def is_dict(self, object):
        return isinstance(object, dict)

    # noinspection PyMethodMayBeStatic
    def is_list(self, object):
        return isinstance(object, list)

    # noinspection PyMethodMayBeStatic
    def in_list(self, item, a_list):
        return item in a_list

    def log(self, message, *ignored):
        message = convert(message)

        if self._debug:
            self._debug.log(message)

        account = self.env.get("account", None)

        if account:
            logging.info("JS: gs #" + str(self.env.get("gamespace", "?")) + " acc @" + str(self.env.get("account", "?")) +
                         " " + str(message))
        else:
            logging.info("JS: gs #" + str(self.env.get("gamespace", "?")) + " " + str(message))

    # noinspection PyMethodMayBeStatic
    def error(self, *args):
        if len(args) >= 2:
            exception = APIUserError(args[0], args[1])
        elif len(args) >= 1 and isinstance(args[0], (Exception, str)):
            exception = APIUserError(500, str(args[0]))
        else:
            exception = APIUserError(500, "Internal Script Error")

        return exception


class JSAPIContext(JSContext):
    def __init__(self, isolate, env, debug=None):
        self.obj = JSAPIEnvironment(env, debug)
        self.env = env
        super(JSAPIContext, self).__init__(obj=self.obj, isolate=isolate)


class CallSession(object):
    def __init__(self, model, function_name, functions, debug, worker, **env):
        self.context = None
        self.debug = debug
        self.gamespace = env["gamespace"]
        self.account_id = env["account"]
        self.env = env
        self.function_name = function_name
        self.functions = functions
        self.model = model
        self.name = ""
        self.worker = worker

    @coroutine
    def init(self):

        self.context = yield self.worker.compile(self.functions, self.env, self.debug)

        self.name = "gamespace {0} / user @{1} / function '{2}'".format(
            self.gamespace, self.account_id, self.function_name)

        logging.info("Session started: " + self.name)

    def call(self, method_name, arguments):
        return self.worker.execute(self.context, method_name, arguments, self.model.call_timeout)

    def eval(self, text):
        return self.worker.eval(self.context, str(text))

    @coroutine
    def release(self, code=0, reason=""):
        try:
            yield self.call("released", {"code": code, "reason": reason or ""})
        except NoSuchMethodError:
            logging.info("This session had no 'released' method to call.")
        except FunctionCallError as e:
            logging.warn("Session release error: " + e.message)
        except Exception as e:
            logging.error("Error while releasing: {0}".format(str(e)))

        logging.info("Session released: @{0}".format(self.name))


class JavascriptWorker(object):
    def __init__(self, name):
        self.name = name

        self._isolate = None
        self._queue = Queue.Queue()
        self._shutdown_lock = Lock()
        self._shutdown = False
        self._thread = Thread(target=self.__thread__, name=name)
        self._thread.start()

    # noinspection PyBroadException
    def __thread__(self):

        self._isolate = JSIsolate()
        ioloop = IOLoop.instance()

        logging.info("Started worker " + str(self.name))

        locker = JSLocker(self._isolate)
        locker.enter()

        self.engine = JSEngine(self._isolate)

        self._isolate.enter()

        try:

            while True:
                item = self._queue.get(block=True)
                if item is None:
                    return

                method, args, future, started = item

                if started:
                    ioloop.spawn_callback(started)

                try:
                    result = method(*args)
                except BaseException as e:
                    ioloop.spawn_callback(future.set_exception, e)
                else:
                    ioloop.spawn_callback(future.set_result, result)

        except BaseException:
            logging.critical('Exception in worker ' + str(self.name), exc_info=True)
        finally:
            self._isolate.leave()
            locker.leave()

    def __terminate__(self):
        self._isolate.terminate()

    def shutdown(self, wait=True):
        with self._shutdown_lock:
            self._shutdown = True
            self._queue.put(None)

        if wait:
            self._thread.join(1000)

    def submit(self, method, args):
        """
        Submits a method into a worker queue.
        Yields result once worker has result.
        """
        with self._shutdown_lock:
            if self._shutdown:
                return None

            future = Future()

            item = (method, args, future, None)

            try:
                self._queue.put_nowait(item)
            except Queue.Full:
                raise APIError(500, "Worker queue is full")

            return future

    @return_future
    def submit_yield(self, method, args, callback):
        """
        Submits a method into a worker queue.
        Yields a future instead of actual result once the job has started.
        The one who asked should yield on the returned future for complete result.

        f = yield worker.submit_yield(__method__, (args...))
        # the job has started here
        result = yield f
        # the job has been completed

        """
        with self._shutdown_lock:
            if self._shutdown:
                return None

            future = Future()

            item = (method, args, future, lambda: callback(future))

            try:
                self._queue.put_nowait(item)
            except Queue.Full:
                raise APIError(500, "Worker queue is full")

    @coroutine
    def eval(self, context, text):
        try:
            f = yield self.submit_yield(JavascriptWorker.__eval__, (context, text,))
            result = yield with_timeout(timeout=datetime.timedelta(milliseconds=FUNCTION_CALL_TIMEOUT), future=f)
        except TimeoutError:
            self.__terminate__()
            raise APICallTimeoutError(
                "Evaluation process timeout: function shouldn't be blocking and "
                "should rely on async methods instead.")

        raise Return(result)

    @coroutine
    def execute(self, context, method, arguments, call_timeout):
        if not isinstance(method, (str, unicode)):
            raise FunctionCallError("Method is not a string")

        if method.startswith("_"):
            raise FunctionCallError("Cannot call such method")

        future = Future()

        f = yield self.submit_yield(self.__execute__, (context, method, arguments, future))

        try:
            immediate_result = yield with_timeout(
                timeout=datetime.timedelta(milliseconds=FUNCTION_CALL_TIMEOUT),
                future=f)

        except TimeoutError:
            self.__terminate__()
            raise APICallTimeoutError(
                "Function '" + method + "' call process timeout: function shouldn't be blocking and "
                "should rely on async methods instead.")

        if immediate_result is not None:
            future.cancel()
            raise Return(immediate_result)

        try:
            result = yield with_timeout(datetime.timedelta(seconds=call_timeout), future)
        except TimeoutError:
            raise FunctionCallError("Total function '{0}' call timeout ({1})".format(
                method, call_timeout))
        except InternalError as e:
            raise APIError(e.code, "Internal error: " + e.body)
        else:
            raise Return(result)

    def precompile(self, functions):
        return self.submit(JavascriptWorker.__precompile__, (self.engine, functions,))

    def compile(self, functions, env, debug):
        return self.submit(JavascriptWorker.__compile__, (self._isolate, self.engine, functions, env, debug,))

    @staticmethod
    def __precompile__(engine, functions):
        result = []

        for name, source in functions:
            try:
                result.append((name, bytearray(engine.precompile(source))))
            except JSError as e:
                raise FunctionCallError(e)
            except Exception as e:
                raise FunctionCallError(str(e))

        return result

    @staticmethod
    def __compile__(isolate, engine, functions, env, debug):

        context = JSAPIContext(isolate, env, debug)

        context.enter()
        try:
            for fn in functions:
                try:
                    script = engine.compile(fn.source, fn.name, -1, -1, fn.precompiled)
                    script.run()
                except JSError as e:
                    raise FunctionCallError("Failed to compile '{0}': ".format(fn.name) + str(e))
                except Exception as e:
                    raise FunctionCallError(str(e))
        finally:
            context.leave()

        return context

    def __execute__(self, context, method, arguments, future):
        context.enter()

        try:
            from api import API

            if not hasattr(context.locals, method):
                raise NoSuchMethodError(method)

            method_function = getattr(context.locals, method, None)

            if not method_function:
                raise NoSuchMethodError(method)

            run_api = API(context, callback=future, worker=self)

            def res(_result):
                IOLoop.instance().spawn_callback(future.set_result, convert(_result))

            try:
                immediate_result = method_function.apply(method_function, [arguments, run_api, res])
            except JSError as e:
                if APIUserError.user(e):
                    code, message = APIUserError.parse(e)
                    raise APIError(code, message)

                raise FunctionCallError(str(e) + "\n" + e.stackTrace)
            except APIError:
                raise
            except Exception as e:
                raise FunctionCallError(str(e))
            else:
                if immediate_result:
                    return convert(immediate_result)
        finally:
            context.leave()

    @staticmethod
    def __eval__(context, text):
        context.enter()

        try:
            try:
                result = context.eval(text)
            except JSError as e:
                if APIUserError.user(e):
                    code, message = APIUserError.parse(e)
                    raise APIError(code, message)

                raise FunctionCallError(str(e) + "\n" + e.stackTrace)
            except Exception as e:
                raise FunctionCallError(str(e))

            return convert(result)
        finally:
            context.leave()


class FunctionsCallModel(Model):
    executor = None

    def __init__(self, functions, cache):

        self.call_timeout = options.js_call_timeout

        self.workers = [
            JavascriptWorker("worker-{0}".format(num))
            for num in xrange(0, options.js_workers or multiprocessing.cpu_count())
        ]
        self.next_worker = -1

        self.cache = cache
        self.functions = functions
        self.saved_code = ExpiringDict(max_len=64, max_age_seconds=60)

    @coroutine
    def prepare(self, gamespace_id, function_name, worker, cache=True, debug=None, application_name=None):
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
                function_name,
                application_name=application_name))

            # compile all functions in parallel
            precompiled_functions = yield worker.precompile(functions)

            # collect them together
            result = [
                CompiledFunction(name, source, precompiled)
                for (name, source), (name_, precompiled) in zip(functions, precompiled_functions)
            ]

            self.saved_code[key] = result

        raise Return(result)

    def get_worker(self):
        self.next_worker += 1

        if self.next_worker >= len(self.workers):
            self.next_worker = 0

        return self.workers[self.next_worker]

    @coroutine
    def stopped(self):
        for worker in self.workers:
            worker.shutdown()

    @coroutine
    def started(self):
        pass # faulthandler.enable()

    # noinspection PyTypeChecker
    @coroutine
    def __run_functions__(self, worker, functions, method_name, arguments, debug=None, **env):

        context = yield worker.compile(functions, env, debug)
        result = yield worker.execute(context, method_name, arguments, self.call_timeout)

        raise Return(result)

    @coroutine
    def session(self, function_name, cache=True, debug=None, application_name=None, **env):

        worker = self.get_worker()

        if application_name:
            env["application_name"] = application_name
            logging.info("Session {0}/{1} on worker '{2}'".format(application_name, function_name, worker.name))
        else:
            logging.info("Session {0} on worker '{1}'".format(function_name, worker.name))

        fns = yield self.prepare(env["gamespace"], function_name, worker, cache, debug=debug,
                                 application_name=application_name)
        session = CallSession(self, function_name, fns, debug, worker, **env)
        yield session.init()

        raise Return(session)

    @coroutine
    def call(self, function_name, arguments, method_name="main", cache=True,
             debug=None, application_name=None, **env):

        if not isinstance(arguments, (dict, list)):
            raise FunctionCallError("arguments expected to be a list or dict")

        t = ElapsedTime("Function execution")
        worker = self.get_worker()

        fns = yield self.prepare(env["gamespace"], function_name, worker, cache, application_name=application_name)
        result = yield self.__run_functions__(worker, fns, method_name, arguments, debug, **env)
        logging.info(t.done())

        raise Return(result)

    def call_fn(self, worker, functions, arguments, method_name="main", **env):

        if not isinstance(arguments, (dict, list)):
            raise FunctionCallError("arguments expected to be a list or dict")

        return self.__run_functions__(worker, functions, method_name, arguments, **env)

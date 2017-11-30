import os

from tornado.gen import coroutine, Return, Future, TimeoutError, with_timeout, IOLoop
# noinspection PyUnresolvedReferences
from v8py import JSException, JSPromise, Context, new, JavaScriptTerminated, Script

from api import expose
from common.model import Model
from common.access import InternalError
from common.source import SourceCodeRoot, SourceCommitAdapter, SourceProjectAdapter, SourceCodeError
from common.validate import validate

from session import JavascriptSession, JavascriptSessionError
from util import APIError, PromiseContext, JavascriptCallHandler, JavascriptExecutionError, process_error

import stdlib
from expiringdict import ExpiringDict

from common.options import options
import datetime
import logging
import options as _opts


class JavascriptBuildError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class NoSuchMethod(Exception):
    pass


class NoSuchClass(Exception):
    pass


class JavascriptBuild(object):
    def __init__(self, build_id=None, model=None, source_path=None):
        self.build_id = build_id
        self.model = model
        self.context = Context(timeout=0.5)
        self.promise_type = self.context.glob.Promise

        # this variable holds amount of users of this build. once this variable hits back to zero,
        # a 30 sec timer will start to release this build
        self.refs = 0
        self._remove_timeout = None

        try:
            script = Script(source=stdlib.source, filename=stdlib.name)
            self.context.eval(script)
        except Exception as e:
            logging.exception("Error while compiling stdlib.js")
            raise JavascriptBuildError(500, str(e))

        if source_path:
            for file_name in os.listdir(source_path):
                if not file_name.endswith(".js"):
                    continue

                logging.info("Compiling file {0}".format(os.path.join(source_path, file_name)))

                try:
                    with open(os.path.join(source_path, file_name), 'r') as f:
                        script = Script(source=f.read(), filename=str(file_name))
                        self.context.eval(script)
                except Exception as e:
                    logging.exception("Error while compiling")
                    raise JavascriptBuildError(500, str(e))

        expose(self.context)
        if self.build_id:
            logging.info("Created new build {0}".format(self.build_id))

    @validate(source_code="str", filename="str")
    def add_source(self, source_code, filename=None):
        script = Script(source=str(source_code), filename=str(filename))
        try:
            self.context.eval(script)
        except JSException as e:
            raise JavascriptBuildError(500, e.message)

    @validate(class_name="str_name", args="json_dict")
    def session(self, class_name, args, log=None, debug=None, **env):
        if class_name not in self.context.glob:
            raise NoSuchClass()
        clazz = getattr(self.context.glob, class_name)

        # each 'session' class should have 'SessionClass.allow_session = true' defined
        if not getattr(clazz, "allow_session", False):
            raise NoSuchClass()

        cache = ExpiringDict(10, 60)

        handler = JavascriptCallHandler(cache, env, debug=debug, promise_type=self.promise_type)
        if log:
            handler.log = log
        PromiseContext.current = handler

        try:
            instance = new(clazz, args, env)
        except TypeError:
            raise JavascriptSessionError(500, "Failed to open session: TypeError while construction")
        except JSException as e:
            raise JavascriptSessionError(500, "Failed to open session: " + str(e))

        # declare some usage, session will release it using 'session_released' call
        self.add_ref()
        return JavascriptSession(self, instance, env, log=log, debug=debug,
                                 cache=cache, promise_type=self.promise_type)

    @coroutine
    @validate(method_name="str_name", args="json_dict")
    def call(self, method_name, args, call_timeout=10, **env):

        if method_name.startswith("_"):
            raise NoSuchMethod()

        if method_name in JavascriptSession.CALL_BLACKLIST:
            raise NoSuchMethod()

        instance = self.context.glob

        if not hasattr(instance, method_name):
            raise NoSuchMethod()

        method = getattr(instance, method_name)

        # each plain function should have 'function.allow_call = true' defined
        if not getattr(method, "allow_call", False):
            raise NoSuchMethod()

        handler = JavascriptCallHandler(None, env, promise_type=self.promise_type)
        PromiseContext.current = handler

        # declare some usage until this call is finished
        self.add_ref()

        try:
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

        finally:
            self.remove_ref()

    def add_ref(self):
        if self._remove_timeout:
            IOLoop.current().remove_timeout(self._remove_timeout)
            self._remove_timeout = None

        self.refs += 1

    def __remove_callback__(self):
        if self.build_id:
            logging.info("Build {0} is being released because no usages left.".format(self.build_id))

        self._remove_timeout = None
        IOLoop.current().add_callback(self.release)

    def remove_ref(self):
        self.refs -= 1
        if self.refs <= 0:
            if self._remove_timeout:
                IOLoop.current().remove_timeout(self._remove_timeout)

            self._remove_timeout = IOLoop.current().add_timeout(
                datetime.timedelta(seconds=30), self.__remove_callback__)

    @coroutine
    def session_released(self, session):
        self.remove_ref()

    @coroutine
    def release(self):
        if hasattr(self, "context"):
            del self.context

        if self.build_id:
            logging.info("Build released {0}".format(self.build_id))

        if self.model:
            yield self.model.build_released(self)


class JavascriptBuildsModel(Model):
    def __init__(self, root_dir, sources):
        self.sources = sources
        self.root = SourceCodeRoot(root_dir)
        self.builds = {}

    @staticmethod
    def __get_build_id__(source):
        return str(source.name) + "_" + str(source.repository_commit)

    def validate_repository_url(self, url, ssh_private_key=None):
        return self.root.validate_repository_url(url, ssh_private_key=ssh_private_key)

    @coroutine
    @validate(source=SourceCommitAdapter)
    def get_build(self, source):

        build_id = JavascriptBuildsModel.__get_build_id__(source)
        build = self.builds.get(build_id, None)
        if build:
            raise Return(build)

        try:
            project = self.root.project(source.gamespace_id, source.name,
                                        source.repository_url, source.repository_branch,
                                        source.ssh_private_key)
            yield project.init()
            source_build = project.build(source.repository_commit)
            yield source_build.init()
        except SourceCodeError as e:
            raise JavascriptBuildError(e.code, e.message)

        build = JavascriptBuild(build_id, self, source_build.build_dir)
        self.builds[build_id] = build
        raise Return(build)

    @coroutine
    @validate(project_settings=SourceProjectAdapter, commit="str_name")
    def new_build_by_commit(self, project_settings, commit):

        try:
            project = self.root.project(
                project_settings.gamespace_id, project_settings.name,
                project_settings.repository_url, project_settings.repository_branch,
                project_settings.ssh_private_key)
            yield project.init()
            source_build = project.build(commit)
            yield source_build.init()
        except SourceCodeError as e:
            raise JavascriptBuildError(e.code, e.message)

        build = JavascriptBuild(None, self, source_build.build_dir)
        raise Return(build)

    @validate(project_settings=SourceProjectAdapter)
    def get_project(self, project_settings):
        try:
            project_instance = self.root.project(
                project_settings.gamespace_id, project_settings.name,
                project_settings.repository_url, project_settings.repository_branch,
                project_settings.ssh_private_key)
        except SourceCodeError as e:
            raise JavascriptBuildError(e.code, e.message)
        else:
            return project_instance

    def __add_build__(self, build):
        self.builds[build.build_id] = build

    def __remove_build__(self, build):
        self.builds.pop(build.build_id)

    @coroutine
    def build_released(self, build):
        if build.build_id:
            self.__remove_build__(build)

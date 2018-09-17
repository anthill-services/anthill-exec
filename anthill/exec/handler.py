
from tornado.web import HTTPError

from anthill.common import handler, ElapsedTime
from anthill.common.access import internal, scoped, AccessToken
from anthill.common.internal import Internal, InternalError
from anthill.common.validate import validate
from anthill.common.login import LoginClient, LoginClientError
from anthill.common.jsonrpc import JsonRPCError

from . model.util import JavascriptExecutionError
from . model.build import JavascriptBuild, JavascriptBuildError, JavascriptSessionError, NoSuchClass, NoSuchMethod
from . model.sources import SourceCodeError, NoSuchSourceError, JavascriptSourceError

import ujson
import logging

from anthill.common.options import options
from . import options as _opts


class SessionHandler(handler.JsonRPCWSHandler):
    def __init__(self, application, request, **kwargs):
        super(SessionHandler, self).__init__(application, request, **kwargs)
        self.session = None
        self.internal = Internal()

    def required_scopes(self):
        return ["exec_func_call"]

    def check_origin(self, origin):
        return True

    async def prepared(self, application_name, application_version, class_name):
        await super(SessionHandler, self).prepared(application_name, application_version, class_name)

        sources = self.application.sources

        user = self.current_user
        token = user.token

        gamespace_id = token.get(AccessToken.GAMESPACE)

        try:
            session_args = ujson.loads(self.get_argument("args", "{}"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted argument 'session_args'")

        try:
            source = await sources.get_build_source(gamespace_id, application_name, application_version)
        except SourceCodeError as e:
            raise HTTPError(e.code, e.message)
        except JavascriptSourceError as e:
            raise HTTPError(e.code, e.message)
        except NoSuchSourceError:
            raise HTTPError(404, "No source found for {0}/{1}".format(application_name, application_version))

        builds = self.application.builds

        try:
            build = await builds.get_build(source)
        except JavascriptBuildError as e:
            raise HTTPError(e.code, e.message)

        try:
            self.session = build.session(
                class_name,
                session_args,
                application_name=application_name,
                application_version=application_version,
                gamespace=gamespace_id,
                account=token.account,
                access_scopes=token.scopes)

        except JavascriptSessionError as e:
            raise HTTPError(e.code, e.message)
        except JavascriptExecutionError as e:
            if options.debug:
                logging.error("API Error: \n" + str(e.traceback))
                self.write(str(e.message) + "\n" + str(e.traceback))
                self.set_status(e.code, str(e.message))
                self.finish()
                return
            raise HTTPError(e.code, e.message)
        except NoSuchClass:
            raise HTTPError(404, "No such class")
        except Exception as e:
            logging.exception("Failed during session initialization")
            raise HTTPError(500, str(e))

    async def call(self, method_name, arguments):

        logging.info("Calling method {0}: {1}".format(
            method_name, str(arguments)
        ))

        try:
            result = await self.session.call(method_name, arguments)
        except JavascriptSessionError as e:
            raise JsonRPCError(e.code, e.message)
        except JavascriptExecutionError as e:
            if options.debug:
                raise JsonRPCError(e.code, e.message, e.traceback)
            raise JsonRPCError(e.code, e.message)
        except Exception as e:
            raise JsonRPCError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        return result

    async def on_closed(self):
        if self.session:
            await self.session.release(self.close_code, self.close_reason)
            self.session = None


class SessionDebugHandler(handler.JsonRPCWSHandler):
    def __init__(self, application, request, **kwargs):
        super(SessionDebugHandler, self).__init__(application, request, **kwargs)
        self.build = JavascriptBuild()
        self.session = None

        self.class_name = None
        self.application_name = None
        self.application_version = None
        self.session_args = None

    def required_scopes(self):
        return ["exec_debug"]

    def check_origin(self, origin):
        return True

    async def prepared(self, application_name, application_version, class_name):
        await super(SessionDebugHandler, self).prepared(application_name, application_version, class_name)
        self.class_name = class_name

        try:
            self.session_args = ujson.loads(self.get_argument("args", "{}"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted argument 'session_args'")

        self.application_name = application_name
        self.application_version = application_version

    def _log_js(self, message):
        logging.info(message)
        self.send_rpc(self, "log", message=message)

    async def start(self):
        if self.session:
            raise JsonRPCError(409, "Session has been initialized already.")

        token = self.token

        gamespace_id = token.get(AccessToken.GAMESPACE)
        account_id = token.account

        try:
            self.session = self.build.session(
                self.class_name,
                self.session_args,
                log=self._log_js,
                application_name=self.application_name,
                application_version=self.application_version,
                gamespace=gamespace_id,
                account=account_id,
                access_scopes=token.scopes)

        except JavascriptSessionError as e:
            raise JsonRPCError(e.code, e.message)
        except JavascriptExecutionError as e:
            if options.debug:
                logging.error("API Error: \n" + str(e.traceback))
                self.write(str(e.message) + "\n" + str(e.traceback))
                self.set_status(e.code, str(e.message))
                self.finish()
                return
            raise JsonRPCError(e.code, e.message)
        except Exception as e:
            logging.exception("Failed during session initialization")
            raise JsonRPCError(500, str(e))

    @validate(text="str")
    async def eval(self, text):
        time = ElapsedTime("Evaluating: {0}".format(text))

        try:
            result = await self.session.eval(text)
        except JavascriptSessionError as e:
            raise JsonRPCError(404, str(e))
        except Exception as e:
            raise JsonRPCError(500, str(e))
        finally:
            logging.info(time.done())

        return {
            "result": result
        }

    @validate(filename="str_name", contents="str")
    async def upload(self, filename, contents):
        if self.session:
            raise JsonRPCError(409, "Session has been initialized already.")

        try:
            self.build.add_source(source_code=contents, filename=filename)
        except JavascriptBuildError as e:
            raise JsonRPCError(e.code, e.message)

    async def call(self, method_name, arguments):

        if not self.session:
            raise JsonRPCError(405, "Session has not been initialized yet.")

        logging.info("Calling method {0}: {1}".format(
            method_name, str(arguments)
        ))

        try:
            result = await self.session.call(method_name, arguments)
        except JavascriptSessionError as e:
            raise JsonRPCError(e.code, e.message)
        except JavascriptExecutionError as e:
            if options.debug:
                raise JsonRPCError(e.code, e.message, e.traceback)
            raise JsonRPCError(e.code, e.message)
        except Exception as e:
            raise JsonRPCError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        return result

    async def on_closed(self):
        if self.session:
            await self.session.release(self.close_code, self.close_reason)
            self.session = None


class CallActionHandler(handler.AuthenticatedHandler):
    @scoped(scopes=["exec_func_call"])
    async def post(self, application_name, application_version, method_name):

        builds = self.application.builds
        sources = self.application.sources

        gamespace_id = self.token.get(AccessToken.GAMESPACE)
        account_id = self.token.account

        try:
            source = await sources.get_build_source(gamespace_id, application_name, application_version)
        except SourceCodeError as e:
            raise HTTPError(e.code, e.message)
        except JavascriptSourceError as e:
            raise HTTPError(e.code, e.message)
        except NoSuchSourceError:
            raise HTTPError(404, "No source found for {0}/{1}".format(application_name, application_version))

        try:
            build = await builds.get_build(source)
        except JavascriptBuildError as e:
            raise HTTPError(e.code, e.message)

        try:
            args = ujson.loads(self.get_argument("args", "{}"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted args, expected to be a dict or list.")

        try:
            result = await build.call(
                method_name, args,
                application_name=application_name,
                application_version=application_version,
                gamespace=gamespace_id,
                account=account_id)

        except JavascriptSessionError as e:
            raise HTTPError(e.code, e.message)
        except JavascriptExecutionError as e:
            if options.debug:
                logging.error("API Error: \n" + str(e.traceback))
                self.write(str(e.message) + "\n" + str(e.traceback))
                self.set_status(e.code, str(e.message))
                self.finish()
                return
            raise HTTPError(e.code, e.message)
        except NoSuchMethod:
            raise HTTPError(404, "No such method")
        except Exception as e:
            raise HTTPError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        self.dumps(result)


class CallServerActionHandler(handler.AuthenticatedHandler):
    @internal
    async def post(self, gamespace_name, method_name):

        builds = self.application.builds
        sources = self.application.sources

        login_client = LoginClient(self.application.cache)

        try:
            gamespace_info = await login_client.find_gamespace(gamespace_name)
        except LoginClientError as e:
            raise HTTPError(e.code, e.message)

        gamespace_id = gamespace_info.gamespace_id

        try:
            source = await sources.get_server_source(gamespace_id)
        except SourceCodeError as e:
            raise HTTPError(e.code, e.message)
        except JavascriptSourceError as e:
            raise HTTPError(e.code, e.message)
        except NoSuchSourceError:
            raise HTTPError(404, "No server source found for gamespace {0}".format(gamespace_name))

        try:
            build = await builds.get_server_build(source)
        except JavascriptBuildError as e:
            raise HTTPError(e.code, e.message)

        try:
            args = ujson.loads(self.get_argument("args", "{}"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted args, expected to be a dict or list.")

        try:
            env = ujson.loads(self.get_argument("env", "{}"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted env, expected to be a dict.")

        env["gamespace"] = gamespace_id

        try:
            result = await build.call(method_name, args, **env)
        except JavascriptSessionError as e:
            raise HTTPError(e.code, e.message)
        except JavascriptExecutionError as e:
            raise HTTPError(e.code, e.message)
        except NoSuchMethod:
            raise HTTPError(404, "No such method")
        except Exception as e:
            raise HTTPError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        self.dumps(result)


class InternalHandler(object):
    def __init__(self, application):
        self.application = application

    @validate(gamespace="int", application_name="str_name", application_version="str", method_name="str_name",
              args="json_dict", env="json_dict")
    async def call_function(self, gamespace, application_name, application_version, method_name, args, env):

        env["gamespace"] = gamespace
        env["application_name"] = application_name
        env["application_version"] = application_version

        builds = self.application.builds
        sources = self.application.sources

        try:
            source = await sources.get_build_source(gamespace, application_name, application_version)
        except SourceCodeError as e:
            raise InternalError(e.code, e.message)
        except JavascriptSourceError as e:
            raise InternalError(e.code, e.message)
        except NoSuchSourceError:
            raise InternalError(404, "No source found for {0}/{1}".format(application_name, application_version))

        try:
            build = await builds.get_build(source)
        except JavascriptBuildError as e:
            raise InternalError(e.code, e.message)

        try:
            result = await build.call(method_name, args, **env)
        except JavascriptSessionError as e:
            raise InternalError(e.code, e.message)
        except JavascriptExecutionError as e:
            raise InternalError(e.code, e.message)
        except Exception as e:
            raise InternalError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        return result

    @validate(gamespace="int", method_name="str_name", args="json_dict", env="json_dict")
    async def call_server_function(self, gamespace, method_name, args, env):

        env["gamespace"] = gamespace

        builds = self.application.builds
        sources = self.application.sources

        try:
            source = await sources.get_server_source(gamespace)
        except SourceCodeError as e:
            raise InternalError(e.code, e.message)
        except JavascriptSourceError as e:
            raise InternalError(e.code, e.message)
        except NoSuchSourceError:
            raise InternalError(404, "No default source found")

        try:
            build = await builds.get_server_build(source)
        except JavascriptBuildError as e:
            raise InternalError(e.code, e.message)

        try:
            result = await build.call(method_name, args, **env)
        except JavascriptSessionError as e:
            raise InternalError(e.code, e.message)
        except JavascriptExecutionError as e:
            raise InternalError(e.code, e.message)
        except Exception as e:
            raise InternalError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        return result

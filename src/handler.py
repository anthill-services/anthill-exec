import common.access

from tornado.web import HTTPError
from tornado.gen import coroutine, Return

from common.access import scoped, AccessToken
import common.handler

from model.fcall import FunctionCallError, APIError, NoSuchMethodError
from model.function import FunctionNotFound
from common.jsonrpc import JsonRPCError

import ujson


class CallSessionHandler(common.handler.JsonRPCWSHandler):
    def __init__(self, application, request, **kwargs):
        super(CallSessionHandler, self).__init__(application, request, **kwargs)
        self.session = None

    def required_scopes(self):
        return ["exec_func_call"]

    @coroutine
    def prepared(self, application_name, function_name):
        yield super(CallSessionHandler, self).prepared()

        user = self.current_user
        token = user.token

        fcalls = self.application.fcalls
        gamespace_id = token.get(AccessToken.GAMESPACE)

        try:
            self.session = yield fcalls.session(
                application_name, function_name,
                gamespace=gamespace_id,
                account=token.account)

        except NoSuchMethodError as e:
            raise HTTPError(404, str(e))
        except FunctionCallError as e:
            raise HTTPError(500, e.message)
        except APIError as e:
            raise HTTPError(e.code, e.message)
        except FunctionNotFound:
            raise HTTPError(404, "No such function")
        except Exception as e:
            raise HTTPError(500, str(e))

    @coroutine
    def call(self, method_name, arguments):
        try:
            result = yield self.session.call(method_name, arguments)
        except NoSuchMethodError as e:
            raise JsonRPCError(404, self.session.name + " " + str(e))
        except FunctionCallError as e:
            raise JsonRPCError(500, self.session.name + " " + e.message)
        except APIError as e:
            raise JsonRPCError(e.code, e.message)
        except FunctionNotFound:
            raise JsonRPCError(404, "No such function")
        except Exception as e:
            raise JsonRPCError(500, str(e))

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        raise Return(result)

    @coroutine
    def closed(self):
        if self.session:
            yield self.session.release()


class CallActionHandler(common.handler.AuthenticatedHandler):
    @coroutine
    @scoped(scopes=["exec_func_call"])
    def post(self, application_name, function_name):

        fcalls = self.application.fcalls

        gamespace_id = self.token.get(AccessToken.GAMESPACE)

        method = self.get_argument("method", "main")

        try:
            args = ujson.loads(self.get_argument("args", "{}"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted args, expected to be a dict or list.")

        try:
            result = yield fcalls.call(application_name, function_name, args,
                                       method_name=method,
                                       gamespace=gamespace_id,
                                       account=self.token.account)

        except NoSuchMethodError as e:
            raise HTTPError(404, str(e))
        except FunctionCallError as e:
            raise HTTPError(500, e.message)
        except APIError as e:
            raise HTTPError(e.code, e.message)
        except FunctionNotFound:
            raise HTTPError(404, "No such function")

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        self.dumps(result)

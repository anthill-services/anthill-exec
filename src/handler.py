
import common.access

from tornado.web import HTTPError
from tornado.gen import coroutine

from common.access import scoped, AccessToken
import common.handler

from model.fcall import FunctionCallError, APIError
from model.function import FunctionNotFound

import ujson


class CallActionHandler(common.handler.AuthenticatedHandler):
    @coroutine
    @scoped(scopes=["exec_func_call"])
    def post(self, application_name, function_name):

        fcalls = self.application.fcalls

        gamespace_id = self.token.get(AccessToken.GAMESPACE)

        try:
            args = ujson.loads(self.get_argument("args", "[]"))
        except (KeyError, ValueError):
            raise HTTPError(400, "Corrupted args.")

        try:
            result = yield fcalls.call(application_name, function_name, args,
                                       gamespace=gamespace_id,
                                       account=self.token.account)

        except FunctionCallError as e:
            raise HTTPError(500, e.message)
        except APIError as e:
            raise HTTPError(e.code, e.message)
        except FunctionNotFound:
            raise HTTPError(404, "No such function")

        if not isinstance(result, (str, dict, list)):
            result = str(result)

        self.dumps(result)

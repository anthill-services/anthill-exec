import json

from tornado.gen import coroutine, Return
from tornado.ioloop import IOLoop
from tornado.websocket import WebSocketClosedError

import common.admin as a

from model.function import FunctionNotFound, FunctionExists, FunctionError, Imports
from model.fcall import FunctionCallError, APIError, NoSuchMethodError
from model.api import AUTOCOMPLETE_LIST

from common.environment import AppNotFound
from common.access import AccessToken
from common.internal import Internal, InternalError
from common.validate import validate
from common import ElapsedTime
from common.jsonrpc import JsonRPCError

from datetime import datetime
import logging


class ApplicationController(a.AdminController):
    @coroutine
    @validate(record_id="str")
    def get(self, record_id):

        env_service = self.application.env_service
        functions = self.application.functions

        try:
            app = yield env_service.get_app_info(self.gamespace, record_id)
        except AppNotFound as e:
            raise a.ActionError("App was not found.")

        result = {
            "app_id": record_id,
            "app_record_id": app["id"],
            "app_name": app["title"],
            "functions": (yield functions.list_bounded_functions(self.gamespace, record_id)),
            "unbounded_functions": {
                fn.function_id: fn.name
                for fn in (yield functions.list_unbounded_functions(self.gamespace, record_id))
                },
        }

        raise a.Return(result)

    @coroutine
    @validate(function_id="int")
    def bind(self, function_id=0):
        if not function_id:
            raise a.ActionError("Nothing to bind")

        functions = self.application.functions

        record_id = self.context.get("record_id")

        try:
            yield functions.bind_function(self.gamespace, record_id, function_id)
        except FunctionExists:
            raise a.ActionError("This function already bound.")
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("app",
                         message="Function has been bound",
                         record_id=record_id)

    def render(self, data):
        return [
            a.breadcrumbs([
                a.link("apps", "Applications")
            ], data["app_name"]),
            a.links("Bound functions (click to unbind)", links=[
                a.link("unbind", fn.name, icon="code", record_id=self.context.get("record_id"),
                       function_id=fn.function_id) for fn in data["functions"]
                ]),
            a.form("Bind new function to this application", fields={
                "function_id": a.field("Function", "select", "primary", "number", values=data["unbounded_functions"])
            }, methods={
                "bind": a.method("Bind", "primary")
            }, data=data),
            a.links("Navigate", [
                a.link("apps", "Go back", icon="chevron-left"),
                a.link("/environment/app", "Manage app '{0}' at 'Environment' service.".format(data["app_name"]),
                       icon="link text-danger", record_id=data["app_record_id"]),
            ])
        ]

    def access_scopes(self):
        return ["exec_admin"]


class UnbindFunctionController(a.AdminController):
    @coroutine
    @validate(function_id="int", record_id="str")
    def get(self, function_id, record_id):

        env_service = self.application.env_service
        functions = self.application.functions

        if not function_id:
            raise a.ActionError("Nothing to unbind")

        try:
            app = yield env_service.get_app_info(self.gamespace, record_id)
        except AppNotFound as e:
            raise a.ActionError("App was not found.")

        try:
            yield functions.unbind_function(self.gamespace, record_id, function_id)
        except FunctionExists:
            raise a.ActionError("This function already bound.")
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("app",
                         message="Function has been unbound",
                         record_id=record_id)

    def access_scopes(self):
        return ["exec_admin"]


class ApplicationsController(a.AdminController):
    @coroutine
    def get(self):
        env_service = self.application.env_service
        apps = yield env_service.list_apps(self.gamespace)

        result = {
            "apps": apps
        }

        raise a.Return(result)

    def render(self, data):
        return [
            a.breadcrumbs([], "Applications"),
            a.links("Select application", links=[
                a.link("app", app_name, icon="mobile", record_id=app_id)
                for app_id, app_name in data["apps"].iteritems()
                ]),
            a.links("Navigate", [
                a.link("index", "Go back", icon="chevron-left"),
                a.link("/environment/apps", "Manage apps", icon="link text-danger"),
            ])
        ]

    def access_scopes(self):
        return ["exec_admin"]


class RootAdminController(a.AdminController):
    def render(self, data):
        return [
            a.links("Exec service", [
                a.link("functions", "Functions", icon="code"),
                a.link("apps", "Applications", icon="mobile")
            ])
        ]

    def access_scopes(self):
        return ["exec_admin"]


class FunctionsController(a.AdminController):
    def render(self, data):
        return [
            a.breadcrumbs([], "Functions"),
            a.links("Functions", [
                a.link("function", f.name, icon="code", function_name=f.name)
                for f in data["functions"]
                ]),
            a.notice("Notice", "Please note that the function should be bound "
                               "to the application in order to be called."),
            a.links("Navigate", [
                a.link("index", "Go back", icon="chevron-left"),
                a.link("new_function", "New function", icon="plus"),
            ])
        ]

    @coroutine
    def get(self):
        functions = self.application.functions

        raise Return({
            "functions": (yield functions.list_functions(self.gamespace))
        })

    def access_scopes(self):
        return ["exec_admin"]


class NewFunctionController(a.AdminController):
    def render(self, data):
        return [
            a.breadcrumbs([
                a.link("functions", "Functions")
            ], "New function"),
            a.form("New function", fields={
                "name": a.field("Function Name", "text", "primary", "non-empty", order=2),
                "imports": a.field("Function Imports", "tags", "primary", order=3),
                "code": a.field("Javascript Code", "code", "primary", "non-empty", order=1),
            }, methods={
                "create": a.method("Create", "primary")
            }, data=data),
            a.links("Navigate", [
                a.link("functions", "Go back", icon="chevron-left")
            ])
        ]

    @coroutine
    @validate(name="str_name", code="str", imports="str")
    def create(self, name, code, imports):
        functions = self.application.functions

        imports = Imports.parse(imports)

        try:
            yield functions.create_function(self.gamespace, name, code, imports)
        except FunctionExists:
            raise a.ActionError("Such function already exists!")
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("function",
                         message="New function has been created",
                         function_name=name)

    @coroutine
    def get(self):
        example = ("function main(args, api, res)\n"
                   "{\n"
                   "    res('Hello, world!');\n"
                   "}")

        raise Return({
            "code": example
        })

    def access_scopes(self):
        return ["exec_admin"]


class FunctionController(a.AdminController):
    def render(self, data):
        return [
            a.breadcrumbs([
                a.link("functions", "Functions")
            ], data["name"]),
            a.form("Function", fields={
                "name": a.field("Function Name", "text", "primary", "non-empty", order=2),
                "imports": a.field("Function Imports", "tags", "primary", order=3),
                "code": a.field("Javascript Code", "code", "primary", "non-empty", order=1, height=400,
                                autocomplete=data["autocomplete"]),
            }, methods={
                "update": a.method("Update", "primary"),
                "delete": a.method("Delete", "danger")
            }, data=data, id="function"),
            a.links("Navigate", [
                a.link("functions", "Go back", icon="chevron-left"),
                a.link("debug_function", "Debug this function", icon="bug",
                       function_id=data["function_id"])
            ])
        ]

    @coroutine
    def delete(self, **ignored):
        functions = self.application.functions

        function_name = self.context.get("function_name")

        try:
            function = yield functions.find_function(self.gamespace, function_name)
        except FunctionNotFound:
            raise a.ActionError("No such function")

        function_id = function.function_id

        try:
            yield functions.delete_function(self.gamespace, function_id)
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("functions",
                         message="Function has been deleted")

    @coroutine
    @validate(name="str_name", code="str", imports="str")
    def update(self, name, code, imports):
        functions = self.application.functions

        function_name = self.context.get("function_name")

        try:
            function = yield functions.find_function(self.gamespace, function_name)
        except FunctionNotFound:
            raise a.ActionError("No such function")

        function_id = function.function_id

        imports = Imports.parse(imports)

        try:
            yield functions.update_function(self.gamespace, function_id, name, code, imports)
        except FunctionExists:
            raise a.ActionError("Such function already exists!")
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("function",
                         message="Function has been updated",
                         function_name=function_name)

    @coroutine
    @validate(function_name="str_name")
    def get(self, function_name):
        functions = self.application.functions

        try:
            function = yield functions.find_function(self.gamespace, function_name)
        except FunctionNotFound:
            raise a.ActionError("No such function")

        raise Return({
            "code": function.code,
            "name": function.name,
            "function_id": function.function_id,
            "imports": function.imports,
            "autocomplete": AUTOCOMPLETE_LIST
        })

    def access_scopes(self):
        return ["exec_admin"]


class DebugFunctionController(a.AdminController):
    def render(self, data):
        r = [
            a.breadcrumbs([
                a.link("functions", "Functions"),
                a.link("function", data["name"], function_name=data["name"])
            ], "Debug")
        ]

        if data["session"]:
            r.extend([
                a.script("static/admin/fn_debug.js",
                         account=data["account"],
                         application_name=data["application_name"],
                         function_name=data["name"])
            ])
        else:
            r.extend([
                a.form("Debug function <b>{0}</b>".format(data["name"]), fields={
                    "credential": a.field("Credential", "text", "primary", "non-empty", order=2),
                    "application_name": a.field("Application Context", "select", "primary", "non-empty", order=3,
                                                values=data["apps"])
                }, methods={
                    "start_session": a.method("Start debug session", "primary")
                }, data=data, icon="bug"),
            ])

        r.extend([
            a.links("Navigate", [
                a.link("function", "Go back", icon="chevron-left", function_id=self.context.get("function_id"))
            ])
        ])

        return r

    @coroutine
    @validate(arguments="load_json", credential="str", application_name="str")
    def start_session(self, credential, application_name, **ignored):
        function_id = self.context.get("function_id")

        raise a.Redirect("debug_function",
                         function_id=function_id,
                         application_name=application_name,
                         credential=credential)

    @coroutine
    @validate(function_id="int", application_name="str", credential="str")
    def get(self, function_id, application_name=None, credential=None):
        env_service = self.application.env_service

        apps = yield env_service.list_apps(self.gamespace)

        functions = self.application.functions

        try:
            function = yield functions.get_function(self.gamespace, function_id)
        except FunctionNotFound:
            raise a.ActionError("No such function")

        session = False
        account = 0

        if application_name and credential:
            internal = Internal()
            try:
                account = yield internal.request(
                    "login",
                    "get_account",
                    credential=credential)

            except InternalError as e:
                if e.code == 400:
                    raise a.ActionError("Failed to find credential: bad username")
                if e.code == 404:
                    raise a.ActionError("Failed to find credential: no such user")

                raise a.ActionError(e.body)
            else:
                account = account["id"]

            session = True

        raise Return({
            "name": function.name,
            "application_name": application_name,
            "credential": credential or self.token.name,
            "session": session,
            "account": account,
            "apps": apps,
            "arguments": {}
        })

    def access_scopes(self):
        return ["exec_admin"]


class FunctionDebugStreamController(a.StreamAdminController):
    def __init__(self, app, token, handler):
        super(FunctionDebugStreamController, self).__init__(app, token, handler)

        class Debug(object):
            def __init__(self, controller):
                self._controller = controller

            # noinspection PyProtectedMember
            def log(self, message):
                IOLoop.current().add_callback(self._controller._log, message=message)

        self.session = None
        self.debug = Debug(self)

    def access_scopes(self):
        return ["exec_admin"]

    @coroutine
    def _log(self, message):
        message = "[" + str(datetime.now()) + "] " + str(message)
        try:
            yield self.send_rpc(self, "log", message=message)
        except JsonRPCError:
            pass

    @coroutine
    @validate(account="int", application_name="str_name", function_name="str_name")
    def on_opened(self, account, application_name, function_name):
        fcalls = self.application.fcalls

        if not account:
            raise a.ActionError("Bad account")

        try:
            self.session = yield fcalls.session(
                function_name, cache=False, debug=self.debug, application_name=application_name,
                gamespace=self.gamespace, account=account)

        except NoSuchMethodError as e:
            raise a.StreamCommandError(404, str(e))
        except FunctionCallError as e:
            raise a.StreamCommandError(500, e.message)
        except APIError as e:
            raise a.StreamCommandError(e.code, e.message)
        except FunctionNotFound:
            raise a.StreamCommandError(404, "No function can be found for that application")
        except Exception as e:
            raise a.StreamCommandError(500, str(e))

        logging.info("Session has been opened!")
        yield self._log("Session started!")

    @coroutine
    @validate(method_name="str", arguments="json_dict")
    def call(self, method_name, arguments):

        if not self.session:
            return

        time = ElapsedTime("Calling method {0}".format(method_name))

        try:
            result = yield self.session.call(method_name, arguments)
        except NoSuchMethodError as e:
            raise a.StreamCommandError(404, str(e))
        except FunctionCallError as e:
            raise a.StreamCommandError(500, e.message)
        except APIError as e:
            raise a.StreamCommandError(e.code, e.message)
        except FunctionNotFound:
            raise a.StreamCommandError(404, "No such function")
        except Exception as e:
            logging.exception("Error while calling method {0}".format(method_name))
            raise a.StreamCommandError(500, str(e))
        finally:
            yield self._log(time.done())

        raise Return(result)

    @coroutine
    @validate(text="str")
    def eval(self, text):

        time = ElapsedTime("Evaluating")

        try:
            result = yield self.session.eval(text)
        except NoSuchMethodError as e:
            raise a.StreamCommandError(404, str(e))
        except FunctionCallError as e:
            raise a.StreamCommandError(500, e.message)
        except APIError as e:
            raise a.StreamCommandError(e.code, e.message)
        except FunctionNotFound:
            raise a.StreamCommandError(404, "No such function")
        except Exception as e:
            raise a.StreamCommandError(500, str(e))
        finally:
            yield self._log(time.done())

        raise Return({
            "result": result
        })

    @coroutine
    def on_closed(self):
        if self.session:
            yield self.session.release(self.handler.close_code, self.handler.close_reason)
            self.session = None

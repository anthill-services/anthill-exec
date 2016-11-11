import json

from tornado.gen import coroutine, Return

import common.admin as a

from model.function import FunctionNotFound, FunctionExists, FunctionError, Imports

from common.environment import AppNotFound
from common import to_int


class ApplicationController(a.AdminController):
    @coroutine
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
    def bind(self, function_id=0):

        function_id = to_int(function_id)

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
                a.link("apps", "Go back"),
                a.link("/environment/app", "Manage app '{0}' at 'Environment' service.".format(data["app_name"]),
                       icon="link text-danger", record_id=data["app_record_id"]),
            ])
        ]

    def access_scopes(self):
        return ["exec_admin"]


class UnbindFunctionController(a.AdminController):
    @coroutine
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
                a.link("index", "Go back"),
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
                a.link("function", f.name, icon="code", function_id=f.function_id)
                for f in data["functions"]
            ]),
            a.notice("Notice", "Please note that the function should be bound "
                               "to the application in order to be called."),
            a.links("Navigate", [
                a.link("index", "Go back"),
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
                "name": a.field("Function Name", "text", "primary", "non-empty", order=1),
                "imports": a.field("Function Imports", "tags", "primary", order=2),
                "code": a.field("Javascript Code", "code", "primary", "non-empty", order=3),
            }, methods={
                "create": a.method("Create", "primary")
            }, data=data),
            a.links("Navigate", [
                a.link("functions", "Go back")
            ])
        ]

    @coroutine
    def create(self, name, code, imports):
        functions = self.application.functions

        imports = Imports.parse(imports)

        try:
            function_id = yield functions.create_function(self.gamespace, name, code, imports)
        except FunctionExists:
            raise a.ActionError("Such function already exists!")
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("function",
                         message="New function has been created",
                         function_id=function_id)

    @coroutine
    def get(self):
        example = ("function main()\n"
                   "{\n"
                   "    res('test');\n"
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
            a.form("New function", fields={
                "name": a.field("Function Name", "text", "primary", "non-empty", order=1),
                "imports": a.field("Function Imports", "tags", "primary", order=2),
                "code": a.field("Javascript Code", "code", "primary", "non-empty", order=3),
            }, methods={
                "update": a.method("Update", "primary"),
                "delete": a.method("Delete", "danger")
            }, data=data),
            a.links("Navigate", [
                a.link("functions", "Go back")
            ])
        ]

    @coroutine
    def delete(self, **ignored):
        functions = self.application.functions

        function_id = self.context.get("function_id")

        try:
            yield functions.delete_function(self.gamespace, function_id)
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("functions",
                         message="Function has been deleted")

    @coroutine
    def update(self, name, code, imports):
        functions = self.application.functions

        function_id = self.context.get("function_id")

        imports = Imports.parse(imports)

        try:
            yield functions.update_function(self.gamespace, function_id, name, code, imports)
        except FunctionExists:
            raise a.ActionError("Such function already exists!")
        except FunctionError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("function",
                         message="Function has been updated",
                         function_id=function_id)

    @coroutine
    def get(self, function_id):
        functions = self.application.functions

        try:
            function = yield functions.get_function(self.gamespace, function_id)
        except FunctionNotFound:
            raise a.ActionError("No such function")

        raise Return({
            "code": function.code,
            "name": function.name,
            "imports": function.imports
        })

    def access_scopes(self):
        return ["exec_admin"]
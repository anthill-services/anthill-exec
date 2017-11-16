
from tornado.gen import coroutine, Return, with_timeout, TimeoutError
from tornado.web import HTTPError
from tornado.ioloop import IOLoop
from tornado.websocket import WebSocketClosedError

import common.admin as a

from model.sources import NoSuchSourceError, SourceCodeError, JavascriptSourceError
from model.build import JavascriptBuildError, NoSuchClass, NoSuchMethod
from model.session import APIError, JavascriptSessionError

from common.environment import AppNotFound
from common.access import AccessToken
from common.internal import Internal, InternalError
from common.validate import validate
from common import ElapsedTime
from common.jsonrpc import JsonRPCError
from common.source import NoSuchProjectError, SourceCodeRoot

from datetime import datetime, timedelta

import traceback
import logging
import ujson


class ApplicationController(a.AdminController):
    @coroutine
    @validate(app_id="str")
    def get(self, app_id):

        env_service = self.application.env_service
        sources = self.application.sources

        try:
            app = yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            has_no_settings = True
        else:
            has_no_settings = False

        result = {
            "app_id": app_id,
            "app_record_id": app["id"],
            "app_name": app["title"],
            "versions": app["versions"],
            "has_no_settings": has_no_settings,
            "public_ssh_key": self.application.builds.ssh_public_key
        }

        raise a.Return(result)

    def render(self, data):
        r = [
            a.breadcrumbs([
                a.link("apps", "Applications")
            ], data["app_name"])
        ]

        if data["has_no_settings"]:
            r.append(ApplicationSettingsController.no_settings_notice())

        r.extend([
            a.links("Application '{0}' versions".format(data["app_name"]), links=[
                a.link("app_version", v_name, icon="tags", app_id=self.context.get("app_id"),
                       app_version=v_name) for v_name, v_id in data["versions"].iteritems()
            ]),
            a.links("Navigate", [
                a.link("app_settings", "Application Settings", icon="cogs", app_id=self.context.get("app_id")),
                a.link("apps", "Go back", icon="chevron-left"),
                a.link("/environment/app", "Manage app '{0}' at 'Environment' service.".format(data["app_name"]),
                       icon="link text-danger", record_id=data["app_record_id"]),
            ])
        ])

        return r

    def access_scopes(self):
        return ["exec_admin"]


class ApplicationSettingsController(a.AdminController):
    @coroutine
    @validate(app_id="str")
    def get(self, app_id):

        env_service = self.application.env_service
        sources = self.application.sources

        try:
            app = yield env_service.get_app_info(app_id)
        except AppNotFound as e:
            raise a.ActionError("App was not found.")

        try:
            project = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            repository_url = ""
            repository_branch = SourceCodeRoot.DEFAULT_BRANCH
        else:
            repository_url = project.repository_url
            repository_branch = project.repository_branch

        result = {
            "app_id": app_id,
            "app_record_id": app["id"],
            "app_name": app["title"],
            "public_ssh_key": self.application.builds.ssh_public_key,
            "repository_url": repository_url,
            "repository_branch": repository_branch
        }

        raise a.Return(result)

    @coroutine
    @validate(name="str_name", code="str", imports="str")
    def update_settings(self, repository_url, repository_branch, *ignored):

        app_id = self.context.get("app_id")

        env_service = self.application.env_service
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield env_service.get_app_info(app_id)
        except AppNotFound as e:
            raise a.ActionError("App was not found.")

        if not (yield builds.validate_repository_url(repository_url)):
            raise a.ActionError("Error: \"{0}\" is not a valid Git repository URL, or "
                                "the repository does not exist.".format(repository_url))

        yield sources.update_project(self.gamespace, app_id, repository_url, repository_branch)
        raise a.Redirect("app_settings",
                         message="Application settings have been updated.",
                         app_id=app_id)

    @staticmethod
    def no_settings_notice():
        return a.notice(
            "Source Code Repository Is Not Configured",
            """
                You have not defined your source code repository yet. <br>
                To deploy your codebase to the Exec service, you must use a Git repository. <br>
                Please create one if you don't have it and define it in the settings below.
            """, style="danger")

    def render(self, data):
        r = [
            a.breadcrumbs([
                a.link("apps", "Applications"),
                a.link("app", data["app_name"], app_id=self.context.get("app_id")),
            ], "Application Settings")]

        if not data["repository_url"]:
            r.append(ApplicationSettingsController.no_settings_notice())

        r.extend([
            a.form("Application Settings", fields={
                "repository_url": a.field(
                    "Git source code repository url (ssh only)", "text", "primary",
                    description="""
                        You need to use SSH remote url in order to deploy source code to this service. See 
                        <a href="https://help.github.com/articles/which-remote-url-should-i-use/#cloning-with-ssh-urls"
                        target="_blank">this</a>.
                    """, order=1),
                "repository_branch": a.field(
                    "Git branch to use on the source code repository", "text", "primary",
                    order=2),
                "public_ssh_key": a.field(
                    "Public SSH key", "readonly", "primary",
                    multiline=3, description="""
                                Please add this SSH key into user's SSH keys with read access to the repository above.
                                For example, on GitHub, it can be done <a href="https://github.com/settings/keys" 
                                target="_blank">here</a>.
                            """, order=3)
            }, methods={
                "update_settings": a.method("Update Settings", "primary")
            }, data=data),
            a.links("Navigate", [
                a.link("app", "Go back", icon="chevron-left", app_id=self.context.get("app_id")),
                a.link("/environment/app", "Manage app '{0}' at 'Environment' service.".format(data["app_name"]),
                       icon="link text-danger", record_id=data["app_record_id"]),
            ])
        ])

        return r

    def access_scopes(self):
        return ["exec_admin"]


class ApplicationVersionController(a.AdminController):
    @coroutine
    @validate(app_id="str", app_version="str")
    def get(self, app_id, app_version):

        env_service = self.application.env_service
        sources = self.application.sources
        builds = self.application.builds

        try:
            app = yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            project_settings = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            raise a.Redirect("app_settings", message="Please define project settings first", app_id=app_id)

        try:
            commit = yield sources.get_commit(self.gamespace, app_id, app_version)
        except NoSuchSourceError:
            current_commit = None
        else:
            current_commit = commit.repository_commit

        try:
            project = builds.get_project(project_settings)
            yield with_timeout(timedelta(seconds=10), project.init())

        except JavascriptBuildError as e:
            raise a.ActionError(e.message)
        except TimeoutError as e:
            commits_history = None
        else:
            try:
                commits_history = yield project.get_commits_history(amount=50)
            except SourceCodeError as e:
                raise a.ActionError(e.message)

        result = {
            "app_id": app_id,
            "app_record_id": app["id"],
            "app_name": app["title"],
            "versions": app["versions"],
            "current_commit": current_commit,
            "commits_history": commits_history,
            "public_ssh_key": self.application.builds.ssh_public_key
        }

        raise a.Return(result)

    @staticmethod
    def no_commit_notice(app_version):
        return a.notice(
            "This version ({0}) is disabled".format(app_version),
            """
                The version {0} is not attached to any commit for the Git repository. <br>
                Therefore, running source code for this version is not possible. <br>
                Please attach the version to a commit using either "Update To The Last Commit", 
                or by clicking "Use This" on a commit of the resent commits history.
            """.format(app_version), style="danger")

    @coroutine
    def switch_commit_context(self):
        commit = self.context.get("commit")
        yield self.switch_commit(commit)

    @coroutine
    def switch_to_latest_commit(self):

        app_id = self.context.get("app_id")
        app_version = self.context.get("app_version")

        env_service = self.application.env_service
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            project_settings = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            raise a.Redirect("app_settings", message="Please define project settings first", app_id=app_id)

        try:
            project = builds.get_project(project_settings)
            yield with_timeout(timedelta(seconds=10), project.init())

        except JavascriptBuildError as e:
            raise a.ActionError(e.message)
        except TimeoutError:
            raise a.ActionError("Repository has not updated itself yet.")

        try:
            latest_commit = yield project.pull_and_get_latest_commit()
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if not latest_commit:
            raise a.ActionError("Failed to check the latest commit")

        try:
            updated = yield sources.update_commit(self.gamespace, app_id, app_version, latest_commit)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if updated:
            raise a.Redirect(
                "app_version",
                message="Version has been updated",
                app_id=app_id, app_version=app_version)

        raise a.Redirect(
            "app_version",
            message="Already up-to-date.",
            app_id=app_id, app_version=app_version)

    @coroutine
    def detach_version(self):

        app_id = self.context.get("app_id")
        app_version = self.context.get("app_version")

        env_service = self.application.env_service
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            deleted = yield sources.delete_commit(self.gamespace, app_id, app_version)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if deleted:
            raise a.Redirect(
                "app_version",
                message="Version has been disabled",
                app_id=app_id, app_version=app_version)

        raise a.Redirect(
            "app_version",
            message="Version was already disabled",
            app_id=app_id, app_version=app_version)

    @coroutine
    def pull_updates(self):

        app_id = self.context.get("app_id")
        app_version = self.context.get("app_version")

        env_service = self.application.env_service
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            project_settings = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            raise a.Redirect("app_settings", message="Please define project settings first", app_id=app_id)

        try:
            project = builds.get_project(project_settings)
            yield with_timeout(timedelta(seconds=10), project.init())

        except JavascriptBuildError as e:
            raise a.ActionError(e.message)
        except TimeoutError:
            raise a.ActionError("Repository has not updated itself yet.")

        try:
            pulled = yield project.pull()
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if not pulled:
            raise a.ActionError("Failed to pull updates")

        raise a.Redirect(
            "app_version",
            message="Updates has been pulled.",
            app_id=app_id, app_version=app_version)

    @coroutine
    @validate(commit="str_name")
    def switch_commit(self, commit):

        app_id = self.context.get("app_id")
        app_version = self.context.get("app_version")

        env_service = self.application.env_service
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            project_settings = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            raise a.Redirect("app_settings", message="Please define project settings first", app_id=app_id)

        try:
            project = builds.get_project(project_settings)
            yield with_timeout(timedelta(seconds=10), project.init())

        except JavascriptBuildError as e:
            raise a.ActionError(e.message)
        except TimeoutError:
            raise a.ActionError("Repository has not updated itself yet.")

        try:
            commit_exists = yield project.check_commit(commit)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if not commit_exists:
            raise a.ActionError("No such commit")

        try:
            yield sources.update_commit(self.gamespace, app_id, app_version, commit)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("app_version", message="Version has been updated", app_id=app_id, app_version=app_version)

    def render(self, data):
        r = [
            a.breadcrumbs([
                a.link("apps", "Applications"),
                a.link("app", data["app_name"], app_id=self.context.get("app_id")),
            ], self.context.get("app_version"))
        ]
        if data["commits_history"] is None:
            r.append(a.notice("Repository is in progress", "Please wait until repository is updated"))
        else:
            methods = {
                "switch_to_latest_commit": a.method("Update To The Last Commit", "primary", order=1),
                "pull_updates": a.method("Pull Updates", "default", order=2),
            }

            if data["current_commit"]:
                methods["detach_version"] = a.method(
                    "Disable This Version", "danger", order=3,
                    danger="Are you sure you would like to disable this version from launching? After this action, "
                           "users would not be able to open sessions on this version.")
            else:
                r.append(ApplicationVersionController.no_commit_notice(self.context.get("app_version")))

            r.extend([
                a.form("Actions", fields={}, methods=methods, data=data),
                a.content(title="Recent Commits History", headers=[
                    {
                        "id": "actions",
                        "title": "Actions"
                    },
                    {
                        "id": "message",
                        "title": "Commit Message"
                    },
                    {
                        "id": "hash",
                        "title": "Commit Hash"
                    },
                    {
                        "id": "date",
                        "title": "Commit Date"
                    },
                    {
                        "id": "author",
                        "title": "Commit Author"
                    },
                    {
                        "id": "debug",
                        "title": "Debug"
                    }
                ], items=[
                    {
                        "hash": [
                            a.status(commit.hexsha[:7], "default")
                        ],
                        "message": commit.message,
                        "date": str(commit.committed_datetime),
                        "author": str(commit.author.name) + " (" + commit.author.email + ")",
                        "actions": [
                            a.status("Current Commit", "success", "check")
                            if data["current_commit"] == commit.hexsha else
                            a.button("app_version", "Use This", "primary", _method="switch_commit_context",
                                     commit=str(commit.hexsha), app_id=self.context.get("app_id"),
                                     app_version=self.context.get("app_version"))
                        ],
                        "debug": [
                            a.link("debug_commit", "", "bug", app_id=self.context.get("app_id"),
                                   app_version=self.context.get("app_version"), commit=str(commit.hexsha))
                        ]
                    }
                    for commit in data["commits_history"]
                ], style="primary")
            ])

        r.extend([
            a.links("Navigate", [
                a.link("app", "Go back", icon="chevron-left", app_id=self.context.get("app_id"))
            ])
        ])

        return r

    def access_scopes(self):
        return ["exec_admin"]


class ApplicationsController(a.AdminController):
    @coroutine
    def get(self):
        env_service = self.application.env_service
        apps = yield env_service.list_apps()

        result = {
            "apps": apps
        }

        raise a.Return(result)

    def render(self, data):
        return [
            a.breadcrumbs([], "Applications"),
            a.links("Select application", links=[
                a.link("app", app_name, icon="mobile", app_id=app_id)
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


class DebugCommitController(a.AdminController):
    def render(self, data):
        r = [
            a.breadcrumbs([
                a.link("apps", "Applications"),
                a.link("app", data["app_name"], app_id=self.context.get("app_id")),
                a.link("app_version", self.context.get("app_version"),
                       app_id=self.context.get("app_id"), app_version=self.context.get("app_version")),
            ], "Debug Commit {0}".format(self.context.get("commit")))
        ]

        if data["session"]:
            r.extend([
                a.script("static/admin/fn_debug.js",
                         account=data["account"],
                         application_name=self.context.get("app_id"),
                         application_version=self.context.get("app_version"),
                         class_name=self.context.get("class_name"),
                         session_args=self.context.get("session_args"),
                         commit=self.context.get("commit"))
            ])
        else:
            r.extend([
                a.form("Debug commit <b>{0}</b>".format(self.context.get("commit")), fields={
                    "credential": a.field("Credential", "text", "primary", "non-empty", order=2),
                    "class_name": a.field("Class Name", "text", "primary", "non-empty", order=3),
                    "session_args": a.field("Arguments Upon Start", "json", "primary", "non-empty",
                                            order=4, height=200)
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
    @validate(arguments="load_json", credential="str", class_name="str_name", session_args="load_json_dict")
    def start_session(self, credential, class_name, session_args, **ignored):
        app_id = self.context.get("app_id")
        app_version = self.context.get("app_version")
        commit = self.context.get("commit")

        raise a.Redirect("debug_commit",
                         app_id=app_id,
                         app_version=app_version,
                         commit=commit,
                         class_name=class_name,
                         session_args=session_args,
                         credential=credential)

    @coroutine
    @validate(app_id="str_name", app_version="str_name", commit="str_name", class_name="str_name",
              credential="str", session_args="json_dict")
    def get(self, app_id, app_version, commit, class_name=None, credential=None, session_args=None):
        env_service = self.application.env_service

        try:
            app = yield env_service.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        session = False
        account = 0

        if class_name and credential:
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
            "app_name": app["title"],
            "credential": credential or self.token.name,
            "session": session,
            "account": account,
            "session_args": {}
        })

    def access_scopes(self):
        return ["exec_admin"]


class CommitDebugStreamController(a.StreamAdminController):
    def __init__(self, app, token, handler):
        super(CommitDebugStreamController, self).__init__(app, token, handler)

        class Debug(object):
            def __init__(self, controller):
                self._controller = controller

        self.session = None
        self.build = None
        self.debug = Debug(self)

    def access_scopes(self):
        return ["exec_admin"]

    def _log(self, message):
        message = "[" + str(datetime.now()) + "] " + str(message)
        try:
            IOLoop.current().add_callback(self.send_rpc, self, "log", message=message)
        except JsonRPCError:
            pass

    @coroutine
    @validate(account="int", application_name="str_name", application_version="str_name", commit="str_name",
              class_name="str_name", session_args="json_dict")
    def prepared(self, account, application_name, application_version, commit, class_name, session_args):
        if not account:
            raise a.ActionError("Bad account")

        sources = self.application.sources

        try:
            project_settings = yield sources.get_project(self.gamespace, application_name)
        except SourceCodeError as e:
            raise a.ActionError(e.message)
        except JavascriptSourceError as e:
            raise a.ActionError(e.message)
        except NoSuchProjectError:
            raise a.ActionError("No such project found: {0}".format(application_name))

        builds = self.application.builds

        try:
            self.build = yield builds.new_build_by_commit(project_settings, commit)
        except JavascriptBuildError as e:
            raise a.ActionError(e.message)

        try:
            self.session = self.build.session(
                class_name,
                session_args,
                log=self._log,
                debug=self.debug,
                application_name=application_name,
                application_version=application_version,
                gamespace=self.gamespace,
                account=self.token.account)

        except JavascriptSessionError as e:
            raise HTTPError(000 + e.code, e.message)
        except NoSuchClass as e:
            raise HTTPError(404, "No such class defined: {0}".format(class_name))
        except APIError as e:
            raise HTTPError(e.code, e.message)
        except Exception as e:
            raise HTTPError(500, str(e))

        # define instance for debugging purposes
        self.build.context.glob.instance = self.session.instance

    @coroutine
    def on_started(self, *args, **kwargs):

        logging.info("Session has been opened!")
        self._log("Session started!")

    @coroutine
    @validate(method_name="str", arguments="json_dict")
    def call(self, method_name, arguments):

        if not self.session:
            return

        time = ElapsedTime("Calling method {0}".format(method_name))

        try:
            result = yield self.session.call(method_name, arguments)
        except JavascriptSessionError as e:
            raise a.StreamCommandError(e.code, str(e))
        except APIError as e:
            raise a.StreamCommandError(e.code, str(e) + "\n" + traceback.format_exc())
        except Exception as e:
            logging.exception("Error while calling method {0}".format(method_name))
            raise a.StreamCommandError(500, str(e))
        finally:
            self._log(time.done())

        raise Return(result)

    @coroutine
    @validate(text="str")
    def eval(self, text):

        time = ElapsedTime("Evaluating")

        try:
            result = yield self.session.eval(text)
        except JavascriptSessionError as e:
            raise a.StreamCommandError(404, str(e))
        except Exception as e:
            raise a.StreamCommandError(500, str(e))
        finally:
            self._log(time.done())

        raise Return({
            "result": result
        })

    @coroutine
    def on_closed(self):
        if self.session:
            yield self.session.release(self.handler.close_code, self.handler.close_reason)
            self.session = None
        if self.build:
            yield self.build.release()
            self.build = None

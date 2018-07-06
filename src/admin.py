
from tornado.gen import coroutine, Return, with_timeout, TimeoutError
from tornado.web import HTTPError
from tornado.ioloop import IOLoop
from tornado.websocket import WebSocketClosedError

import common.admin as a

from model.sources import NoSuchSourceError, SourceCodeError, JavascriptSourceError
from model.build import JavascriptBuildError, NoSuchClass, NoSuchMethod
from model.session import APIError, JavascriptSessionError

from common.environment import EnvironmentClient, AppNotFound
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

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources

        try:
            app = yield environment_client.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError:
            has_no_settings = True
            commits = {}
        else:
            has_no_settings = False
            try:
                commits = yield sources.list_versions(self.gamespace, app_id)
            except SourceCodeError:
                commits = {}

        result = {
            "app_id": app_id,
            "app_record_id": app.id,
            "app_name": app.title,
            "versions": app.versions,
            "commits": commits,
            "has_no_settings": has_no_settings
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

        commits = data["commits"]

        def get_version_commit(version):
            commit = commits.get(version, None)
            if commit is not None:
                return commit.repository_commit[:7]
            return None

        r.extend([
            a.links("Application '{0}' versions".format(data["app_name"]), links=[
                a.link("app_version", v_name, icon="tags", badge=get_version_commit(v_name),
                       app_id=self.context.get("app_id"), app_version=v_name)
                for v_name, v_id in data["versions"].iteritems()
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

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources

        try:
            app = yield environment_client.get_app_info(app_id)
        except AppNotFound as e:
            raise a.ActionError("App was not found.")

        try:
            project = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            repository_url = ""
            ssh_private_key = ""
            repository_branch = SourceCodeRoot.DEFAULT_BRANCH
        else:
            repository_url = project.repository_url
            repository_branch = project.repository_branch
            ssh_private_key = project.ssh_private_key

        result = {
            "app_id": app_id,
            "app_record_id": app.id,
            "app_name": app.title,
            "repository_url": repository_url,
            "repository_branch": repository_branch,
            "ssh_private_key": ssh_private_key
        }

        raise a.Return(result)

    @coroutine
    @validate(repository_url="str", repository_branch="str", ssh_private_key="str")
    def update_settings(self, repository_url, repository_branch, ssh_private_key, *ignored):

        app_id = self.context.get("app_id")

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield environment_client.get_app_info(app_id)
        except AppNotFound as e:
            raise a.ActionError("App was not found.")

        if not (yield builds.validate_repository_url(repository_url, ssh_private_key)):
            raise a.ActionError("Error: \"{0}\" is not a valid Git repository URL, or "
                                "the repository does not exist, or the ssh key is wrong.".format(repository_url))

        yield sources.update_project(self.gamespace, app_id, repository_url, repository_branch, ssh_private_key)
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
                "ssh_private_key": a.field(
                    "Private SSH key", "text", "primary",
                    multiline=6, description="""
                                Please generate SSH key pair, paste private key (for example, 
                                <span class="label label-default">id_rsa</span>) here, and add public key (for example, 
                                <span class="label label-default">id_rsa.pub</span>) into user's SSH keys with 
                                read access to the repository above.
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


class ServerCodeSettingsController(a.AdminController):
    @coroutine
    def get(self):

        sources = self.application.sources

        try:
            project = yield sources.get_server_project(self.gamespace)
        except NoSuchProjectError as e:
            repository_url = ""
            ssh_private_key = ""
            repository_branch = SourceCodeRoot.DEFAULT_BRANCH
        else:
            repository_url = project.repository_url
            repository_branch = project.repository_branch
            ssh_private_key = project.ssh_private_key

        result = {
            "repository_url": repository_url,
            "repository_branch": repository_branch,
            "ssh_private_key": ssh_private_key
        }

        raise a.Return(result)

    @coroutine
    @validate(repository_url="str", repository_branch="str", ssh_private_key="str")
    def update_settings(self, repository_url, repository_branch, ssh_private_key, *ignored):

        sources = self.application.sources
        builds = self.application.builds

        if not (yield builds.validate_repository_url(repository_url, ssh_private_key)):
            raise a.ActionError("Error: \"{0}\" is not a valid Git repository URL, or "
                                "the repository does not exist, or the ssh key is wrong.".format(repository_url))

        yield sources.update_server_project(self.gamespace, repository_url, repository_branch, ssh_private_key)

        raise a.Redirect("server", message="Server Code settings have been updated.")

    @staticmethod
    def no_settings_notice():
        return a.notice(
            "Server Code Repository Is Not Configured",
            """
                You have not defined your source code repository yet. <br>
                To deploy your codebase to the Exec service, you must use a Git repository. <br>
                Please create one if you don't have it and define it in the settings below.
            """, style="danger")

    def render(self, data):
        r = [
            a.breadcrumbs([
                a.link("server", "Server Code"),
            ], "Server Code Settings"),
            ServerCodeController.about_notice()
        ]

        if not data["repository_url"]:
            r.append(ServerCodeSettingsController.no_settings_notice())

        r.extend([
            a.form("Server Code Settings", fields={
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
                "ssh_private_key": a.field(
                    "Private SSH key", "text", "primary",
                    multiline=6, description="""
                                Please generate SSH key pair, paste private key (for example, 
                                <span class="label label-default">id_rsa</span>) here, and add public key (for example, 
                                <span class="label label-default">id_rsa.pub</span>) into user's SSH keys with 
                                read access to the repository above.
                                For example, on GitHub, it can be done <a href="https://github.com/settings/keys" 
                                target="_blank">here</a>.
                            """, order=3)
            }, methods={
                "update_settings": a.method("Update Settings", "primary")
            }, data=data),
            a.links("Navigate", [
                a.link("server", "Go back", icon="chevron-left"),
            ])
        ])

        return r

    def access_scopes(self):
        return ["exec_admin"]


class ApplicationVersionController(a.AdminController):
    @coroutine
    @validate(app_id="str", app_version="str")
    def get(self, app_id, app_version):

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources
        builds = self.application.builds

        try:
            app = yield environment_client.get_app_info(app_id)
        except AppNotFound:
            raise a.ActionError("App was not found.")

        try:
            project_settings = yield sources.get_project(self.gamespace, app_id)
        except NoSuchProjectError as e:
            raise a.Redirect("app_settings", message="Please define project settings first", app_id=app_id)

        try:
            commit = yield sources.get_version_commit(self.gamespace, app_id, app_version)
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
            "app_record_id": app.id,
            "app_name": app.title,
            "versions": app.versions,
            "current_commit": current_commit,
            "commits_history": commits_history
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

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield environment_client.get_app_info(app_id)
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

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield environment_client.get_app_info(app_id)
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

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield environment_client.get_app_info(app_id)
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

        environment_client = EnvironmentClient(self.application.cache)
        sources = self.application.sources
        builds = self.application.builds

        try:
            yield environment_client.get_app_info(app_id)
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
                    }
                ], items=[
                    {
                        "hash": [
                            a.status(commit.hexsha[:7], "default")
                        ],
                        "message": commit.message[:48],
                        "date": str(commit.committed_datetime),
                        "author": str(commit.author.name) + " (" + commit.author.email + ")",
                        "actions": [
                            a.status("Current Commit", "success", "check")
                            if data["current_commit"] == commit.hexsha else
                            a.button("app_version", "Use This", "primary", _method="switch_commit_context",
                                     commit=str(commit.hexsha), app_id=self.context.get("app_id"),
                                     app_version=self.context.get("app_version"))
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


class ServerCodeController(a.AdminController):

    @coroutine
    def get(self):

        sources = self.application.sources
        builds = self.application.builds

        try:
            project_settings = yield sources.get_server_project(self.gamespace)
        except NoSuchProjectError:
            raise a.Redirect("server_settings", message="Please define project settings first")

        try:
            commit = yield sources.get_server_commit(self.gamespace)
        except NoSuchSourceError:
            current_commit = None
        else:
            current_commit = commit.repository_commit

        try:
            project = builds.get_server_project(project_settings)
            yield with_timeout(timedelta(seconds=10), project.init())

        except JavascriptBuildError as e:
            raise a.ActionError(e.message)
        except TimeoutError:
            commits_history = None
        else:
            try:
                commits_history = yield project.get_commits_history(amount=50)
            except SourceCodeError as e:
                raise a.ActionError(e.message)

        result = {
            "current_commit": current_commit,
            "commits_history": commits_history
        }

        raise a.Return(result)

    @staticmethod
    def no_commit_notice():
        return a.notice(
            "The Server Code is disabled",
            """
                The server code is not attached to any commit for the Git repository. <br>
                Therefore, running source code for the server code is not possible. <br>
                Please attach the version to a commit using either "Update To The Last Commit", 
                or by clicking "Use This" on a commit of the resent commits history.
            """, style="danger")

    @staticmethod
    def about_notice():
        return a.notice(
            "About The Server Code",
            """
                The Server Code is a way to deploy restricted application-independent code to the exec service. <br>
                Users cannot call the Server Code, but other services can. Therefore, services that have no
                application context can call functions on exec service with Server Code. <br>
                Please refer to the API for more information.
            """, style="info")

    @coroutine
    def switch_commit_context(self):
        commit = self.context.get("commit")
        yield self.switch_commit(commit)

    @coroutine
    def switch_to_latest_commit(self):

        sources = self.application.sources
        builds = self.application.builds

        try:
            project_settings = yield sources.get_server_project(self.gamespace)
        except NoSuchProjectError:
            raise a.Redirect("server_settings", message="Please define project settings first")

        try:
            project = builds.get_server_project(project_settings)
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
            updated = yield sources.update_server_commit(self.gamespace, latest_commit)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if updated:
            raise a.Redirect("server", message="Server Code has been updated")

        raise a.Redirect("server", message="Already up-to-date.")

    @coroutine
    def detach_version(self):

        sources = self.application.sources

        try:
            deleted = yield sources.delete_server_commit(self.gamespace)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        if deleted:
            raise a.Redirect("server", message="Server code has been disabled")

        raise a.Redirect("server", message="Server code was already disabled")

    @coroutine
    def pull_updates(self):

        sources = self.application.sources
        builds = self.application.builds

        try:
            project_settings = yield sources.get_server_project(self.gamespace)
        except NoSuchProjectError:
            raise a.Redirect("server_settings", message="Please define project settings first")

        try:
            project = builds.get_server_project(project_settings)
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

        raise a.Redirect("server", message="Updates has been pulled.")

    @coroutine
    @validate(commit="str_name")
    def switch_commit(self, commit):

        sources = self.application.sources
        builds = self.application.builds

        try:
            project_settings = yield sources.get_server_project(self.gamespace)
        except NoSuchProjectError as e:
            raise a.Redirect("server_settings", message="Please define project settings first")

        try:
            project = builds.get_server_project(project_settings)
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
            yield sources.update_server_commit(self.gamespace, commit)
        except SourceCodeError as e:
            raise a.ActionError(e.message)

        raise a.Redirect("server", message="Server code commit has been updated")

    def render(self, data):
        r = [
            a.breadcrumbs([], "Server Code")
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
                    "Disable Server Code", "danger", order=3,
                    danger="Are you sure you would like to disable the Server Code from launching? After this action, "
                           "services would not be able to call functions on the Server Code.")
            else:
                r.append(ServerCodeController.no_commit_notice())

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
                    }
                ], items=[
                    {
                        "hash": [
                            a.status(commit.hexsha[:7], "default")
                        ],
                        "message": commit.message[:48],
                        "date": str(commit.committed_datetime),
                        "author": str(commit.author.name) + " (" + commit.author.email + ")",
                        "actions": [
                            a.status("Current Commit", "success", "check")
                            if data["current_commit"] == commit.hexsha else
                            a.button("server", "Use This", "primary", _method="switch_commit_context",
                                     commit=str(commit.hexsha))
                        ]
                    }
                    for commit in data["commits_history"]
                ], style="primary")
            ])

        r.extend([
            ServerCodeController.about_notice(),
            a.links("Navigate", [
                a.link("index", "Go back", icon="chevron-left"),
                a.link("server_settings", "Server Code Settings", icon="cogs")
            ])
        ])

        return r

    def access_scopes(self):
        return ["exec_admin"]


class ApplicationsController(a.AdminController):
    @coroutine
    def get(self):
        environment_client = EnvironmentClient(self.application.cache)
        apps = yield environment_client.list_apps()

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
                a.link("apps", "Applications", icon="mobile"),
                a.link("server", "Server Code", icon="server"),
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

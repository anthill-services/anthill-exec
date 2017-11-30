
from tornado.gen import coroutine

import admin
import handler

import common.access
import common.server
import common.sign
import common.environment
import common.discover
import common.database
import common.keyvalue
import common.source

from model.sources import JavascriptSourcesModel
from model.build import JavascriptBuildsModel

from common.options import options
import options as _opts


class ExecServer(common.server.Server):
    def __init__(self, db=None):
        super(ExecServer, self).__init__()

        db = db or common.database.Database(
            host=options.db_host,
            database=options.db_name,
            user=options.db_username,
            password=options.db_password)

        self.cache = common.keyvalue.KeyValueStorage(
            host=options.cache_host,
            port=options.cache_port,
            db=options.cache_db,
            max_connections=options.cache_max_connections)

        self.sources = JavascriptSourcesModel(db)
        self.builds = JavascriptBuildsModel(options.source_dir, self.sources)

        self.env_service = common.environment.EnvironmentClient(self.cache)

    def get_models(self):
        return [self.sources, self.builds]

    def get_internal_handler(self):
        return handler.InternalHandler(self)

    def get_admin(self):
        return {
            "index": admin.RootAdminController,
            "apps": admin.ApplicationsController,
            "app": admin.ApplicationController,
            "app_version": admin.ApplicationVersionController,
            "app_settings": admin.ApplicationSettingsController
        }

    def get_metadata(self):
        return {
            "title": "Exec",
            "description": "Execute custom javascript code server-side",
            "icon": "code"
        }

    def get_handlers(self):
        return [
            (r"/call/(\w+)/(.*)/(\w+)", handler.CallActionHandler),
            (r"/session/(\w+)/(.*)/(\w+)", handler.SessionHandler),
            (r"/debug/(\w+)/(.*)/(\w+)", handler.SessionDebugHandler)
        ]


if __name__ == "__main__":
    stt = common.server.init()
    common.access.AccessToken.init([common.access.public()])
    common.server.start(ExecServer)

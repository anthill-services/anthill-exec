
from . import admin
from . import handler

from anthill.common import access, server, database, keyvalue

from . model.sources import JavascriptSourcesModel
from . model.build import JavascriptBuildsModel

from anthill.common.options import options
from . import options as _opts


class ExecServer(server.Server):
    def __init__(self, db=None):
        super(ExecServer, self).__init__()

        db = db or database.Database(
            host=options.db_host,
            database=options.db_name,
            user=options.db_username,
            password=options.db_password)

        self.cache = keyvalue.KeyValueStorage(
            host=options.cache_host,
            port=options.cache_port,
            db=options.cache_db,
            max_connections=options.cache_max_connections)

        self.sources = JavascriptSourcesModel(db)
        self.builds = JavascriptBuildsModel(options.js_source_path, self.sources)

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
            "app_settings": admin.ApplicationSettingsController,
            "server": admin.ServerCodeController,
            "server_settings": admin.ServerCodeSettingsController
        }

    def get_metadata(self):
        return {
            "title": "Exec",
            "description": "Execute custom javascript code server-side",
            "icon": "code"
        }

    def get_handlers(self):
        return [
            (r"/server/(\w+)/(\w+)", handler.CallServerActionHandler),
            (r"/call/(\w+)/(.*)/(\w+)", handler.CallActionHandler),
            (r"/session/(\w+)/(.*)/(\w+)", handler.SessionHandler),
            (r"/debug/(\w+)/(.*)/(\w+)", handler.SessionDebugHandler)
        ]


if __name__ == "__main__":
    stt = server.init()
    access.AccessToken.init([access.public()])
    server.start(ExecServer)


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

from model.function import FunctionsModel
from model.fcall import FunctionsCallModel

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

        self.functions = FunctionsModel(self, db)
        self.fcalls = FunctionsCallModel(self.functions, self.cache)

        self.env_service = common.environment.EnvironmentClient(self.cache)

    def get_models(self):
        return [self.functions, self.fcalls]

    def get_admin(self):
        return {
            "index": admin.RootAdminController,
            "apps": admin.ApplicationsController,
            "app": admin.ApplicationController,
            "unbind": admin.UnbindFunctionController,
            "functions": admin.FunctionsController,
            "new_function": admin.NewFunctionController,
            "function": admin.FunctionController
        }

    def get_metadata(self):
        return {
            "title": "Exec",
            "description": "Execute custom javascript code server-side",
            "icon": "code"
        }

    def get_handlers(self):
        return [
            (r"/call/(\w+)/(.*)", handler.CallActionHandler)
        ]


if __name__ == "__main__":
    stt = common.server.init()
    common.access.AccessToken.init([common.access.public()])
    common.server.start(ExecServer)

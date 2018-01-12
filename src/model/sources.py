
from tornado.gen import coroutine, Return

from common.validate import validate
from common.model import Model
from common.source import DatabaseSourceCodeRoot, NoSuchSourceError, SourceCodeError


class JavascriptSourceError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return str(self.code) + ": " + self.message


class JavascriptSourcesModel(Model, DatabaseSourceCodeRoot):
    def __init__(self, db):
        self.db = db
        Model.__init__(self)
        DatabaseSourceCodeRoot.__init__(self, self.db, "exec")

    def get_setup_db(self):
        return self.db

    def get_setup_tables(self):
        return ["exec_application_settings", "exec_application_versions", "exec_server"]

    @coroutine
    @validate(gamespace_id="int", application_name="str", application_version="str")
    def get_build_source(self, gamespace_id, application_name, application_version):
        try:
            result = yield self.get_version_commit(gamespace_id, application_name, application_version)
        except SourceCodeError as e:
            raise JavascriptSourceError(e.code, e.message)
        except NoSuchSourceError:
            raise JavascriptSourceError(404, "No such source for {0}/{1}".format(
                application_name,
                application_version
            ))
        raise Return(result)

    @coroutine
    @validate(gamespace_id="int")
    def get_server_source(self, gamespace_id):
        try:
            result = yield self.get_server_commit(gamespace_id)
        except SourceCodeError as e:
            raise JavascriptSourceError(e.code, e.message)
        except NoSuchSourceError:
            raise JavascriptSourceError(404, "No default source")
        raise Return(result)

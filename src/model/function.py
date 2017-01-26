
import re

from tornado.gen import coroutine, Return
from common.database import DatabaseError, DuplicateError, ConstraintsError
from common.model import Model

IMPORTS_PATTERN = re.compile("^([A-Za-z0-9_]+)$")
IMPORTS_STR_PATTERN = re.compile("^([A-Za-z0-9_,]+)?$")


class FunctionAdapter(object):
    def __init__(self, data):
        self.function_id = data.get("function_id")
        self.name = data.get("function_name")
        self.code = data.get("function_code")
        self.imports = data.get("function_imports")


class FunctionNotFound(Exception):
    pass


class FunctionExists(Exception):
    pass


class FunctionError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class Imports(object):
    @staticmethod
    def validate(imports):

        if not isinstance(imports, list):
            return False

        return all(bool(re.match(IMPORTS_PATTERN, imp)) for imp in imports)

    @staticmethod
    def parse(imports):

        if imports == "":
            return []

        if re.match(IMPORTS_STR_PATTERN, imports):
            return imports.split(",")

        return None

    @staticmethod
    def dump(imports):
        return ",".join(imports)


class FunctionsModel(Model):
    def __init__(self, app, db):
        self.db = db
        self.app = app

    def get_setup_db(self):
        return self.db

    @coroutine
    def setup_table_configurations(self):
        pass

    def get_setup_tables(self):
        return ["functions", "application_functions"]

    @coroutine
    def delete_function(self, gamespace_id, function_id):

        try:
            yield self.db.execute(
                """
                    DELETE FROM `functions`
                    WHERE `function_id`=%s AND `gamespace_id`=%s;
                """, function_id, gamespace_id)
        except ConstraintsError:
            raise FunctionError("Unbind the function from applications first")
        except DatabaseError as e:
            raise FunctionError("Failed to delete function: " + e.args[1])

    @coroutine
    def unbind_function(self, gamespace_id, application_name, function_id):

        try:
            yield self.db.execute(
                """
                    DELETE FROM `application_functions`
                    WHERE `application_name`=%s AND `function_id`=%s AND `gamespace_id`=%s;
                """, application_name, function_id, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to delete app function: " + e.args[1])

    @coroutine
    def get_function(self, gamespace_id, function_id):

        try:
            function = yield self.db.get(
                """
                    SELECT *
                    FROM `functions`
                    WHERE `function_id`=%s AND `gamespace_id`=%s;
                """, function_id, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to get function: " + e.args[1])

        if not function:
            raise FunctionNotFound()

        raise Return(FunctionAdapter(function))

    @coroutine
    def find_function(self, gamespace_id, function_name):

        try:
            function = yield self.db.get(
                """
                    SELECT *
                    FROM `functions`
                    WHERE `function_name`=%s AND `gamespace_id`=%s;
                """, function_name, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to get function: " + e.args[1])

        if not function:
            raise FunctionNotFound()

        raise Return(FunctionAdapter(function))

    @coroutine
    def find_bound_function(self, gamespace_id, application_name, function_name):

        try:
            function = yield self.db.get(
                """
                    SELECT *
                    FROM `functions`, `application_functions`
                    WHERE `function_name`=%s AND `functions`.`gamespace_id`=%s
                        AND `application_functions`.`application_name`=%s
                        AND `application_functions`.`function_id`=`functions`.`function_id`;
                """, function_name, gamespace_id, application_name)

        except DatabaseError as e:
            raise FunctionError("Failed to get application function: " + e.args[1])

        if not function:
            raise FunctionNotFound()

        raise Return(FunctionAdapter(function))

    @coroutine
    def get_function_with_dependencies(self, gamespace_id, application_name, function_name):

        fn = yield self.find_bound_function(gamespace_id, application_name, function_name)

        try:
            functions = yield self.db.query(
                """
                    SELECT *
                    FROM `functions`
                    WHERE `function_name` IN (%s) AND `gamespace_id`=%s;
                """, fn.imports, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to get function: " + e.args[1])

        result = {
            fn["function_name"]: str(fn["function_code"])
            for fn in functions
        }

        try:
            result[fn.name] = str(fn.code)
        except UnicodeEncodeError:
            raise FunctionError("Unicode characters in source code is not supported")

        raise Return(result)

    @coroutine
    def list_functions(self, gamespace_id):

        try:
            functions = yield self.db.query(
                """
                    SELECT *
                    FROM `functions`
                    WHERE `gamespace_id`=%s;
                """, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to get function: " + e.args[1])

        raise Return(map(FunctionAdapter, functions))

    @coroutine
    def list_bounded_functions(self, gamespace_id, application_name):

        try:
            functions = yield self.db.query(
                """
                    SELECT *
                    FROM `functions`, `application_functions`
                    WHERE `application_functions`.application_name=%s AND `functions`.`gamespace_id`=%s
                      AND `functions`.`function_id`=`application_functions`.`function_id`;
                """, application_name, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to get app functions: " + e.args[1])

        raise Return(map(FunctionAdapter, functions))

    @coroutine
    def list_unbounded_functions(self, gamespace_id, application_name):

        try:
            functions = yield self.db.query(
                """
                    SELECT *
                    FROM `functions`
                    WHERE NOT EXISTS(
                        SELECT function_id
                        FROM `application_functions`
                        WHERE `application_functions`.application_name=%s AND
                            `application_functions`.function_id=`functions`.function_id

                    ) AND `functions`.`gamespace_id`=%s;
                """, application_name, gamespace_id)
        except DatabaseError as e:
            raise FunctionError("Failed to get app functions: " + e.args[1])

        raise Return(map(FunctionAdapter, functions))

    @coroutine
    def create_function(self, gamespace_id, function_name, function_code, function_imports):

        if not Imports.validate(function_imports):
            raise FunctionError("Bad imports")

        try:
            function_id = yield self.db.insert(
                """
                    INSERT INTO `functions`
                    (`gamespace_id`, `function_name`, `function_code`, `function_imports`)
                    VALUES (%s, %s, %s, %s);
                """, gamespace_id, function_name, function_code, Imports.dump(function_imports))
        except DuplicateError:
            raise FunctionExists()
        except DatabaseError as e:
            raise FunctionError("Failed to create a function: " + e.args[1])

        raise Return(function_id)

    @coroutine
    def bind_function(self, gamespace_id, application_name, function_id):

        try:
            yield self.db.insert(
                """
                    INSERT INTO `application_functions`
                    (`gamespace_id`, `application_name`, `function_id`)
                    VALUES (%s, %s, %s);
                """, gamespace_id, application_name, function_id)
        except DuplicateError:
            raise FunctionExists()
        except DatabaseError as e:
            raise FunctionError("Failed to create a app function: " + e.args[1])

    @coroutine
    def update_function(self, gamespace_id, function_id, function_name, function_code, function_imports):

        if not Imports.validate(function_imports):
            raise FunctionError("Bad imports")

        try:
            yield self.db.execute(
                """
                    UPDATE `functions`
                    SET `function_name`=%s, `function_code`=%s, `function_imports`=%s
                    WHERE `function_id`=%s AND `gamespace_id`=%s;
                """, function_name, function_code, Imports.dump(function_imports), function_id, gamespace_id)
        except DuplicateError:
            raise FunctionExists()
        except DatabaseError as e:
            raise FunctionError("Failed to update a function: " + e.args[1])

        raise Return(function_id)

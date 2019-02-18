
from tornado.testing import gen_test

# noinspection PyUnresolvedReferences
from v8py import JSException, Context, new

from .. server import ExecServer
from .. model.build import JavascriptBuildsModel

from git import Repo

import tempfile
import os
import shutil
import ujson

from anthill.common import jsonrpc
from anthill.common.testing import AcceptanceTestCase
from anthill.common.options import options, default
from .. import options as _opts


class ExecAcceptanceTestCase(AcceptanceTestCase):

    @classmethod
    def need_access_token(cls):
        return ["exec_func_call", "exec_debug"]

    TEST_JS = """
        function TestClass()
        {
        }
        
        TestClass.prototype.test_call = async function(args)
        {
            return "test";
        }
        
        TestClass.prototype._test_disallowed = async function(args)
        {
            return "test";
        }
        
        TestClass.allow_session = true;
        
        function NotAllowedClass()
        {
        }
        
        function TestDisallowedClass()
        {
        }
        
        function simple_call(args)
        {
            return "simple_call_test_" + args["arg1"];
        }
        
        simple_call.allow_call = true;
        
        function error_call(args)
        {
            throw new Error(args["code"], args["message"]);
        }
        
        error_call.allow_call = true;
        
        function simple_call_sum(args)
        {
            return args["arg1"] + args["arg2"];
        }
        
        simple_call_sum.allow_call = true;
        
        function simple_call_disallowed()
        {
            return "simple_call_test";
        }
    """

    TEST_SERVER_JS = """
        function test_sum(args)
        {
            return args["arg1"] + args["arg2"];
        }
        
        function test_disallowed(args)
        {
            return "wow!";
        }
        
        test_sum.allow_call = true;
    """

    @classmethod
    def need_test_db(cls):
        return True

    @classmethod
    def get_server_instance(cls, db=None):
        return ExecServer(db)

    @classmethod
    async def setup_repo(cls):
        repo_path = tempfile.mkdtemp()
        repo = Repo.init(repo_path, False)

        test_file_path = os.path.join(repo_path, "test.js")

        with open(test_file_path, "w") as f:
            f.write(ExecAcceptanceTestCase.TEST_JS)
            f.close()

        repo.index.add([test_file_path])
        commit = repo.index.commit("Added test.js")

        test_dir = os.path.join(options.js_source_path, AcceptanceTestCase.TOKEN_GAMESPACE,
                                AcceptanceTestCase.APPLICATION_NAME)

        # delete the test application directory
        if os.path.isdir(test_dir):
            shutil.rmtree(test_dir)

        # bind our temporary repository to test application
        await cls.admin_action(
            "app_settings", "update_settings",
            {
                "app_id": AcceptanceTestCase.APPLICATION_NAME
            },
            repository_url=os.path.join(repo_path, ".git"),
            repository_branch="master",
            ssh_private_key="")

        # bind commit <commit> to test / 0.1
        await cls.admin_action(
            "app_version", "switch_commit",
            {
                "app_id": AcceptanceTestCase.APPLICATION_NAME,
                "app_version": AcceptanceTestCase.APPLICATION_VERSION_NAME
            },
            commit=commit.hexsha)

    @classmethod
    async def setup_server_repo(cls):
        repo_path = tempfile.mkdtemp()
        repo = Repo.init(repo_path, False)

        test_file_path = os.path.join(repo_path, "test_server.js")

        with open(test_file_path, "w") as f:
            f.write(ExecAcceptanceTestCase.TEST_SERVER_JS)
            f.close()

        repo.index.add([test_file_path])
        commit = repo.index.commit("Added test_server.js")

        test_dir = os.path.join(options.js_source_path, AcceptanceTestCase.TOKEN_GAMESPACE,
                                JavascriptBuildsModel.SERVER_PROJECT_NAME)

        # delete the test application directory
        if os.path.isdir(test_dir):
            shutil.rmtree(test_dir)

        # bind our temporary repository to server code
        await cls.admin_action(
            "server_settings", "update_settings", {},
            repository_url=os.path.join(repo_path, ".git"),
            repository_branch="master",
            ssh_private_key="")

        # bind commit <commit> to server code
        await cls.admin_action(
            "server", "switch_commit", {},
            commit=commit.hexsha)

    @classmethod
    async def co_setup_acceptance_tests(cls):
        await cls.setup_repo()
        await cls.setup_server_repo()

    @gen_test
    async def test_bad_initialization_missing(self):
        async def opened(rpc):
            self.fail("Expected to never initialize")

        await self.json_rpc(
            "session/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/MissingClassName", opened,
            do_await=True, expect_error_code=404)

    @gen_test
    async def test_bad_initialization_disallowed(self):
        async def opened(rpc):
            self.fail("Expected to never initialize")

        await self.json_rpc(
            "session/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/TestDisallowedClass", opened,
            do_await=True, expect_error_code=404)

    async def _test_rpc(self, rpc):
        result = await rpc.send_request(rpc, "call", method_name="test_call", arguments={})
        self.assertTrue(result, "test")

        try:
            await rpc.send_request(rpc, "call", method_name="test_missing", arguments={})
        except jsonrpc.JsonRPCError as e:
            self.assertEqual(e.code, 404)
        else:
            self.fail("This method expected to fail with 404 Not Found")

        try:
            await rpc.send_request(rpc, "call", method_name="_test_disallowed", arguments={})
        except jsonrpc.JsonRPCError as e:
            self.assertEqual(e.code, 404)
        else:
            self.fail("This method expected to fail with 404 Not Found")

        rpc.close()

    @gen_test
    async def test_session_calls(self):
        async def opened(rpc):
            await self._test_rpc(rpc)

        await self.json_rpc(
            "session/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/TestClass", opened)

    @gen_test
    async def test_simple_call(self):

        a = await self.post_success(
            "call/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/simple_call", {
                "args": ujson.dumps({
                    "arg1": "argument_a"
                })
            }
        )
        self.assertEqual(a, "simple_call_test_argument_a")

    @gen_test
    async def test_error_call(self):

        await self.post_fail(
            "call/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/error_call", {
                "args": ujson.dumps({
                    "code": 535,
                    "message": "Welp"
                })
            }, expected_code=535, expected_body="Welp")

        await self.post_fail(
            "call/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/error_call", {
                "args": ujson.dumps({
                    "code": 500,
                    "message": "Whoops"
                })
            }, expected_code=500, expected_body="Whoops")

    @gen_test
    async def test_simple_sum(self):

        a = await self.post_success(
            "call/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/simple_call_sum", {
                "args": ujson.dumps({
                    "arg1": 5,
                    "arg2": 7
                })
            }
        )
        self.assertEqual(int(a), 12)

    @gen_test
    async def test_simple_call_missing(self):

        await self.post_fail(
            "call/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/simple_call_missing", {},
            expected_code=404
        )

    @gen_test
    async def test_simple_call_disallowed(self):

        a = await self.post_fail(
            "call/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/simple_call_disallowed", {},
            expected_code=404)

    @gen_test
    async def test_server_sum(self):

        a = await self.post_success(
            "server/" + AcceptanceTestCase.TOKEN_GAMESPACE_NAME + "/test_sum", {
                "args": ujson.dumps({
                    "arg1": 5,
                    "arg2": 7
                })
            }
        )
        self.assertEqual(int(a), 12)

    @gen_test
    async def test_server_missing(self):

        await self.post_fail(
            "server/" + AcceptanceTestCase.TOKEN_GAMESPACE_NAME + "/test_missing", {},
            expected_code=404)

    @gen_test
    async def test_server_disallowed(self):

        await self.post_fail(
            "server/" + AcceptanceTestCase.TOKEN_GAMESPACE_NAME + "/test_disallowed", {},
            expected_code=404)

    @gen_test
    async def test_debug_calls(self):
        async def opened(rpc):

            try:
                await rpc.send_request(rpc, "call", method_name="test_call", arguments={})
            except jsonrpc.JsonRPCError as e:
                self.assertEqual(e.code, 405)
            else:
                self.fail("This method expected to fail with 405 Not initialized yet")

            await rpc.send_request(rpc, "upload", filename="test.js", contents=ExecAcceptanceTestCase.TEST_JS)

            await rpc.send_request(rpc, "start")

            try:
                await rpc.send_request(rpc, "start")
            except jsonrpc.JsonRPCError as e:
                pass
            else:
                self.fail("Expected to fail the second time")

            try:
                await rpc.send_request(rpc, "upload", filename="test.js", contents=ExecAcceptanceTestCase.TEST_JS)
            except jsonrpc.JsonRPCError as e:
                pass
            else:
                self.fail("Upload should not be possible after start")

            call_result = await rpc.send_request(rpc, "eval", text="1+1")
            self.assertEqual(call_result["result"], 2)

            await self._test_rpc(rpc)

        await self.json_rpc(
            "debug/" + AcceptanceTestCase.APPLICATION_NAME + "/" +
            AcceptanceTestCase.APPLICATION_VERSION_NAME + "/TestClass", opened)

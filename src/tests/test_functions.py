from tornado.gen import coroutine, Return, sleep
from tornado.testing import gen_test
from tornado.ioloop import IOLoop

# noinspection PyUnresolvedReferences
from v8py import JSException, Context, new

# noinspection PyUnresolvedReferences
from server import ExecServer

from model.build import JavascriptBuild, JavascriptBuildError, JavascriptSessionError
from model.build import NoSuchClass, NoSuchMethod, JavascriptExecutionError

import options as _opts
from common import random_string, testing
import hashlib
import inspect
import re


def is_debugging():
    for frame in inspect.stack():
        if frame[1].endswith("pydevd.py"):
            return True
    return False


class FunctionsTestCase(testing.ServerTestCase):
    @classmethod
    @coroutine
    def co_setup_class(cls):
        cls.db = yield cls.get_test_db()

        cls.app = ExecServer(cls.db)

        cls.builds = cls.app.builds
        cls.sources = cls.app.sources

        IOLoop.current().set_blocking_log_threshold(0)

        yield cls.app.started()

    @classmethod
    @coroutine
    def co_tear_down_class(cls):
        cls.app.shutdown()

    @coroutine
    def check_build(self, build, name, checks):
        for args, result in checks:
            should_be = yield build.call(name, args)
            self.assertEqual(should_be, result, "Function result is not as expected!")

    @gen_test
    def test_bad_call(self):
        build = JavascriptBuild()

        build.add_source("""
            function sum(a, b)
            {
                return a + b;
            }

            function main(args)
            {
                return sum(args["a"], args["b"]);
            }
        """)

        with self.assertRaises(NoSuchMethod):
            yield build.call("main", {"a": 1, "b": 2})

        with self.assertRaises(NoSuchMethod):
            yield build.call("no_such_method", {"a": 1, "b": 2})

        with self.assertRaises(NoSuchMethod):
            yield build.call("sum", {"a": 1, "b": 2})

        with self.assertRaises(NoSuchMethod):
            yield build.call("Math.sqrt", {"a": 1, "b": 2})

    @gen_test
    def test_callback_sum(self):
        build = JavascriptBuild()

        build.add_source("""
            async function sum(a, b)
            {
                return a + b;
            }

            async function main(args)
            {
                return await sum(args["a"], args["b"]);
            }
            
            main.allow_call = true;
        """)

        self.assertEqual(3, (yield build.call("main", {"a": 1, "b": 2})))
        self.assertEqual(0, (yield build.call("main", {"a": -50, "b": 50})))

    @gen_test
    def test_immediate_sum(self):
        build = JavascriptBuild()

        build.add_source("""
            function sum(a, b)
            {
                return a + b;
            }

            function main(args)
            {
                return sum(args["a"], args["b"]);
            }
            
            main.allow_call = true;
        """)

        self.assertEqual(3, (yield build.call("main", {"a": 1, "b": 2})))
        self.assertEqual(0, (yield build.call("main", {"a": -50, "b": 50})))

    @gen_test
    def test_private_properties(self):
        class TestClass(object):
            def __init__(self):
                self.prop_test_a = 5
                self.prop_test_b = 7

                self.prop_test_c = 9
                self.prop_test_d = 11

            def get_test_a(self): return self.prop_test_a

            def set_test_a(self, value): self.prop_test_a = value

            def get_test_b(self): return self.prop_test_b

            def set_test_b(self, value): self.prop_test_b = value

            def get_test_c(self): return self.prop_test_c

            def set_test_c(self, value): self.prop_test_c = value

            def get_test_d(self): return self.prop_test_d

            def set_test_d(self, value): self.prop_test_d = value

            test_a = property(get_test_a, set_test_a)
            _test_b = property(get_test_b, set_test_b)
            test_c = property(get_test_c, set_test_c)
            _test_d = property(get_test_d, set_test_d)

        instance = TestClass()

        build = JavascriptBuild()

        build.add_source("""
            function main(args)
            {
                var obj = args["instance"];

                obj.test_c = 100
                obj._test_d = 200

                return [
                    obj.test_a,
                    obj._test_b
                ];
            }

            main.allow_call = true;
        """)

        result = yield build.call("main", {"instance": instance})
        self.assertEqual(result, [5, None])

        self.assertEqual(instance.test_c, 100)
        self.assertEqual(instance._test_d, 11)

    @gen_test
    def test_api_error(self):

        build = JavascriptBuild()

        build.add_source("""
            function main(args)
            {
                throw new Error(400, "bad_idea");
            }

            main.allow_call = true;
        """)

        try:
            yield build.call("main", {})
        except JavascriptExecutionError as error:
            self.assertEqual(error.code, 400)
            self.assertEqual(error.message, "bad_idea")
        else:
            self.fail("Expected APIError")

    @gen_test
    def test_api_error_traceback(self):

        build = JavascriptBuild()

        build.add_source("""
        
            function a()
            {
                throw new Error(400, "bad_idea");
            }
        
            function b()
            {
                a();
            }
        
            function c()
            {
                b();
            }
        
            function main(args)
            {
                c();
            }

            main.allow_call = true;
        """, filename="test_api_error.js")

        try:
            yield build.call("main", {})
        except JavascriptExecutionError as error:
            self.assertEqual(error.code, 400)
            self.assertEqual(error.message, "bad_idea")

            if not re.search("\s+File \"test_api_error.js-[0-9]+\", line 20, in main"
                             "\s+c\(\);"
                             "\s+File \"test_api_error\.js-[0-9]+\", line 15, in c"
                             "\s+b\(\);"
                             "\s+File \"test_api_error\.js-[0-9]+\", line 10, in b"
                             "\s+a\(\);"
                             "\s+File \"test_api_error\.js-[0-9]+\", line 5, in a"
                             "\s+throw new Error\(400, \"bad_idea\"\);", error.traceback, re.MULTILINE):
                self.fail("Traceback does not match: " + error.traceback)

        else:
            self.fail("Expected APIError")

    @gen_test
    def test_api_error_callback(self):

        build = JavascriptBuild()

        build.add_source("""
            async function main(args)
            {
                await sleep(0.1)
                throw new Error(400, "bad_idea");
            }

            main.allow_call = true;
        """)

        with self.assertRaises(JavascriptExecutionError) as error:
            yield build.call("main", {})

        self.assertEqual(error.exception.code, 400)
        self.assertEqual(error.exception.message, "bad_idea")

    SHA256 = """
        SHA256={},SHA256.K=[1116352408,1899447441,3049323471,3921009573,961987163,1508970993,2453635748,2870763221,
        3624381080,310598401,607225278,1426881987,1925078388,2162078206,2614888103,3248222580,3835390401,
        4022224774,264347078,604807628,770255983,1249150122,1555081692,1996064986,2554220882,2821834349,
        2952996808,3210313671,3336571891,3584528711,113926993,338241895,666307205,773529912,1294757372,
        1396182291,1695183700,1986661051,2177026350,2456956037,2730485921,2820302411,3259730800,3345764771,
        3516065817,3600352804,4094571909,275423344,430227734,506948616,659060556,883997877,958139571,1322822218,
        1537002063,1747873779,1955562222,2024104815,2227730452,2361852424,2428436474,2756734187,3204031479,
        3329325298],SHA256.Uint8Array=function(a){return"undefined"!=typeof Uint8Array?new Uint8Array(a):new
        Array(a)},SHA256.Int32Array=function(a){return"undefined"!=typeof Int32Array?new Int32Array(a):new
        Array(a)},SHA256.setArray=function(a,b){if("undefined"!=typeof Uint8Array)a.set(b);else{for(var c=0;
        c<b.length;c++)a[c]=b[c];for(c=b.length;c<a.length;c++)a[c]=0}},SHA256.digest=function(a){var b=1779033703,
        c=3144134277,d=1013904242,e=2773480762,f=1359893119,g=2600822924,h=528734635,i=1541459225,j=SHA256.K;
        if("string"==typeof a){var k=unescape(encodeURIComponent(a));a=SHA256.Uint8Array(k.length);for(var l=0;
        l<k.length;l++)a[l]=255&k.charCodeAt(l)}var m=a.length,n=64*Math.floor((m+72)/64),o=n/4,p=8*m,q=
        SHA256.Uint8Array(n);SHA256.setArray(q,a),q[m]=128,q[n-4]=p>>>24,q[n-3]=p>>>16&255,q[n-2]=p>>>8&255,
        q[n-1]=255&p;var r=SHA256.Int32Array(o),s=0;for(l=0;l<r.length;l++){var t=q[s]<<24;t|=q[s+1]<<16,
        t|=q[s+2]<<8,t|=q[s+3],r[l]=t,s+=4}for(var u=SHA256.Int32Array(64),v=0;v<o;v+=16){for(l=0;l<16;l++)u[l]=
        r[v+l];for(l=16;l<64;l++){var w=u[l-15],x=w>>>7|w<<25;x^=w>>>18|w<<14,x^=w>>>3,w=u[l-2];var y=w>>>17|
        w<<15;y^=w>>>19|w<<13,y^=w>>>10,u[l]=u[l-16]+x+u[l-7]+y&4294967295}var z=b,A=c,B=d,C=e,D=f,E=g,F=h,G=i;
        for(l=0;l<64;l++){y=D>>>6|D<<26,y^=D>>>11|D<<21,y^=D>>>25|D<<7;var H=D&E^~D&F,I=G+y+H+j[l]+u[l]&4294967295;
        x=z>>>2|z<<30,x^=z>>>13|z<<19,x^=z>>>22|z<<10;var J=z&A^z&B^A&B,K=x+J&4294967295;G=F,F=E,E=D,D=
        C+I&4294967295,C=B,B=A,A=z,z=I+K&4294967295}b=b+z&4294967295,c=c+A&4294967295,d=d+B&4294967295,e=
        e+C&4294967295,f=f+D&4294967295,g=g+E&4294967295,h=h+F&4294967295,i=i+G&4294967295}var L=
        SHA256.Uint8Array(32);for(l=0;l<4;l++)L[l]=b>>>8*(3-l)&255,L[l+4]=c>>>8*(3-l)&255,L[l+8]=d>>>8*(3-l)&255,
        L[l+12]=e>>>8*(3-l)&255,L[l+16]=f>>>8*(3-l)&255,L[l+20]=g>>>8*(3-l)&255,L[l+24]=h>>>8*(3-l)&255,
        L[l+28]=i>>>8*(3-l)&255;return L},SHA256.hash=function(a){var b=SHA256.digest(a),c="";for(i=0;i<
        b.length;i++){var d="0"+b[i].toString(16);c+=d.length>2?d.substring(1):d}return c};
    """

    @gen_test
    def test_sha(self):

        build = JavascriptBuild()

        build.add_source(FunctionsTestCase.SHA256)
        build.add_source("""
            function test_sha256(args)
            {
                var message = args["i"];
                return SHA256.hash(message);
            }
            
            test_sha256.allow_call = true;
        """)

        yield self.check_build(build, "test_sha256", [
            ({"i": ""}, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            ({"i": "test"}, "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"),
            ({"i": "1"}, "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b"),
            ({"i": "sha-256"}, "3128f8ac2988e171a53782b144b98a5c2ee723489c8b220cece002916fbc71e2")
        ])

    @gen_test
    def test_session_release(self):

        build = JavascriptBuild()

        class Obj(object):
            released = False

        def were_released():
            Obj.released = True

        build.context.expose(were_released)

        build.add_source("""
            function SessionTest()
            {
            }

            SessionTest.prototype.released = async function(args)
            {
                await sleep(0.2)
                were_released();
            };

            SessionTest.allow_session = true;
        """)

        session = build.session("SessionTest", {})
        self.assertEqual(Obj.released, False)
        yield session.release()
        self.assertEqual(Obj.released, True)

    @gen_test
    def test_session(self):

        build = JavascriptBuild()
        build.add_source(FunctionsTestCase.SHA256)

        build.add_source("""
            function SessionTest()
            {
            }
            
            SessionTest.allow_session = true;
            
            SessionTest.prototype.main = async function(args)
            {
                var message = args["message"];
                var time = args["time"];
                
                await sleep(time);
                
                return SHA256.hash(message);
            };
        """)

        session = build.session("SessionTest", {})

        try:
            res = yield [
                session.call("main", {"message": "", "time": 0.5}),
                session.call("main", {"message": "test", "time": 0.2}),
                session.call("main", {"message": "1", "time": 1}),
                session.call("main", {"message": "sha-256", "time": 0.1})
            ]
        finally:
            yield session.release()

        self.assertEqual(res, [
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
            "3128f8ac2988e171a53782b144b98a5c2ee723489c8b220cece002916fbc71e2"])

    @gen_test(timeout=60)
    def test_session_stress(self):

        if is_debugging():
            self.skipTest("Stress test doesn't go well with debugging")

        build = JavascriptBuild()
        build.add_source(FunctionsTestCase.SHA256)

        build.add_source("""
            function SessionTest()
            {
            }
            
            SessionTest.allow_session = true;
            
            SessionTest.prototype.main = async function(args)
            {
                var message = args["message"];
                var time = args["time"];
                
                await sleep(time);
                    
                return SHA256.hash(message);
            };
        """)

        session = build.session("SessionTest", {})

        calls = []
        expected = []

        for i in xrange(0, 10000):
            time = (i % 100) / 100
            rand = random_string(512)
            expected_result = hashlib.sha256(rand).hexdigest()

            calls.append(session.call("main", {"message": rand, "time": time}, call_timeout=20))
            expected.append(expected_result)

        try:
            res = yield calls
        finally:
            yield session.release()

        self.assertEqual(res, expected)

    @gen_test
    def test_context(self):

        build = JavascriptBuild()
        build.add_source(FunctionsTestCase.SHA256)

        build.add_source("""
        
            function ContextTest()
            {
            }
        
            ContextTest.prototype.main = async function(args)
            {
                await sleep(0.5)
                return true;
            }
            
            ContextTest.allow_session = true;
            
        """)

        session = build.session("ContextTest", {})

        @coroutine
        def do_delay():
            """
            This will ensure the functions are called in such order:

            1. first function started
            2. second function started
            3. first function completed
            4. second function completed

            It ensures the v8 context is opened end released correctly

            """

            yield sleep(0.25)
            result = yield session.call("main", {})
            raise Return(result)

        try:
            res = yield [
                session.call("main", {}),
                do_delay(),
            ]
        finally:
            yield session.release()

        self.assertEqual(res, [True, True])

    @gen_test(timeout=1)
    def test_parallel(self):
        """
        This test has timeout 1 because 4 calls (0.5s each) being called in parallel should be
        definitely done within one second
        """

        build = JavascriptBuild()
        build.add_source(FunctionsTestCase.SHA256)

        build.add_source("""

            function ParallelTest()
            {
            }

            ParallelTest.prototype.main = async function(args)
            {
                var a = args["a"];
                var b = args["b"];
                
                await sleep(0.5);

                return a + b;
            }

            ParallelTest.allow_session = true;

        """)

        session = build.session("ParallelTest", {})

        try:
            a = session.call("main", {"a": 1, "b": 2})
            b = session.call("main", {"a": 100, "b": 200})
            c = session.call("main", {"a": -10, "b": 10})
            d = session.call("main", {"a": 100000, "b": 200000})

            # call them in parallel
            res = yield [a, b, c, d]
        finally:
            yield session.release()

        self.assertEqual(res, [3, 300, 0, 300000])

    @gen_test(timeout=1.5)
    def test_timeout(self):
        """
        This function ensures that infinite loops can be caught by timeout
        """

        build = JavascriptBuild()

        build.add_source("""
            function main(args)
            {
                while(true);
            }
            
            main.allow_call = true;
        """)

        with self.assertRaises(JavascriptExecutionError) as error:
            yield build.call("main", {})

        self.assertEqual(error.exception.code, 408)

    @gen_test(timeout=1)
    def test_timeout_in_callback(self):
        """
        This function ensures that infinite loops inside the callbacks also can be caught by timeout
        """

        build = JavascriptBuild()

        build.add_source("""
            async function main(args)
            {
                await sleep(0.1)
                
                while(true);
            }

            main.allow_call = true;
        """)

        with self.assertRaises(JavascriptExecutionError) as error:
            yield build.call("main", {})

        self.assertEqual(error.exception.code, 408)

    @gen_test(timeout=1)
    def test_parallel_api(self):
        build = JavascriptBuild()

        build.add_source("""
            async function main(args)
            {
                var sleep1 = sleep(0.25);
                var sleep2 = sleep(0.5);
                
                await Promise.all([sleep1, sleep2])
            }

            main.allow_call = true;
        """)

        yield build.call("main", {})

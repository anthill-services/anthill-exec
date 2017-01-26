
from tornado.gen import coroutine, Return, sleep
from tornado.testing import gen_test

from server import ExecServer

from model.fcall import NoSuchMethodError, APIError
from model.function import FunctionExists, FunctionNotFound

import common.testing
import options as _opts
from common import random_string
import hashlib


class FunctionsTestCase(common.testing.ServerTestCase):

    @classmethod
    @coroutine
    def co_setup_class(cls):
        cls.db = yield cls.get_test_db()

        cls.app = ExecServer(cls.db)

        cls.functions = cls.app.functions
        cls.fcalls = cls.app.fcalls

        yield cls.app.started()

    @coroutine
    def js_function(self, name, code, checks):
        fn = yield self.functions.create_function(0, name, code, [])
        yield self.functions.bind_function(0, "test_app", fn)

        yield self.check_function("test_app", name, checks)

    @coroutine
    def check_function(self, app_name, name, checks):
        for args, result in checks:
            self.assertEqual(
                (yield self.fcalls.call(app_name, name, args, gamespace=0, account=0)),
                result,
                "Function result is not as expected!")

    @gen_test
    def test_double_bind(self):

        fn = yield self.functions.create_function(
            0, "test_double_bind",
            """
                function main(args)
                {
                    return args[0] + args[1];
                }
            """, [])

        yield self.functions.bind_function(0, "test_app", fn)

        with self.assertRaises(FunctionExists):
            yield self.functions.bind_function(0, "test_app", fn)

    @gen_test
    def test_sum(self):

        yield self.js_function(
            "test_hello",
            """
                function sum(a, b)
                {
                    return a + b;
                }

                function main(args, api)
                {
                    api.res(sum(args[0], args[1]));
                }
            """, checks=[
                ([10, 5], 15),
                ([10, -5], 5)
            ])

    @gen_test
    def test_no_main(self):
        fn = yield self.functions.create_function(
            0, "test_no_main",
            """
                function sum(a, b)
                {
                    return a + b;
                }
            """, [])

        yield self.functions.bind_function(0, "test_app", fn)

        with self.assertRaises(NoSuchMethodError):
            yield self.fcalls.call("test_app", "test_no_main", [0, 1], gamespace=0, account=0)

    @gen_test
    def test_api_error(self):
        fn = yield self.functions.create_function(
            0, "test_api_error",
            """
                function main(args, api)
                {
                    throw error(400, "bad_idea");
                }
            """, [])

        yield self.functions.bind_function(0, "test_app", fn)

        with self.assertRaises(APIError, code=400, message="bad_idea"):
            yield self.fcalls.call("test_app", "test_api_error", [0, 1], gamespace=0, account=0)

    @gen_test
    def test_obj(self):
        fn = yield self.functions.create_function(
            0, "test_obj",
            """
                function main(args, api)
                {
                    var data = args[0];
                    api.res(data["a"] + data["b"]);
                }
            """, [])

        yield self.functions.bind_function(0, "test_app", fn)

        result = yield self.fcalls.call("test_app", "test_obj", [{"a": 5, "b": 20}], gamespace=0, account=0)
        self.assertEqual(result, 25)

    @gen_test
    def test_sha256(self):

        fn1 = yield self.functions.create_function(
            0, "sha256",
            """

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

            """, []
        )

        fn2 = yield self.functions.create_function(
            0, "test_sha256",
            """

            function main(args, api)
            {
                var message = args[0];
                api.res(SHA256.hash(message));
            }

            """, ["sha256"])

        yield self.functions.bind_function(0, "test_app", fn1)
        yield self.functions.bind_function(0, "test_app", fn2)

        yield self.check_function("test_app", "test_sha256", [
            ([""], "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            (["test"], "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"),
            (["1"], "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b"),
            (["sha-256"], "3128f8ac2988e171a53782b144b98a5c2ee723489c8b220cece002916fbc71e2")
        ])

    @gen_test
    def test_session(self):

        fn1 = yield self.functions.create_function(
            0, "sha256_session",
            """

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

            """, []
        )

        fn2 = yield self.functions.create_function(
            0, "test_sha256_session",
            """

            function main(args, api)
            {
                var message = args[0];
                var time = args[1];
                api.sleep(time).done(function()
                {
                    api.res(SHA256.hash(message))
                });
            }

            """, ["sha256_session"])

        yield self.functions.bind_function(0, "test_app", fn1)
        yield self.functions.bind_function(0, "test_app", fn2)

        session = yield self.fcalls.session("test_app", "test_sha256_session", gamespace=0, account=0)

        try:
            res = yield [
                session.call("main", ["", 0.5]),
                session.call("main", ["test", 0.2]),
                session.call("main", ["1", 1]),
                session.call("main", ["sha-256", 0.1])
            ]
        finally:
            yield session.release()

        self.assertEqual(res, [
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
            "3128f8ac2988e171a53782b144b98a5c2ee723489c8b220cece002916fbc71e2"])

    @gen_test
    def test_import(self):
        fn1 = yield self.functions.create_function(
            0, "test_a", """
                function main(args, api)
                {
                    api.res(args["first"] + ":" + test_b(args["second"]));
                }
            """, ["test_b"])

        fn2 = yield self.functions.create_function(
            0, "test_b", """
                function test_b(second, api)
                {
                    return "second:" + second;
                }
            """, [])

        yield self.functions.bind_function(0, "test_app", fn1)

        yield self.check_function(
            "test_app", "test_a", checks=[
                ({"first": "john", "second": "dou"}, "john:second:dou"),
                ({"first": "will", "second": "smith"}, "will:second:smith"),
            ])

    @gen_test
    def test_bad_bind(self):
        fn = yield self.functions.create_function(
            0, "test_bad_bind", """
                function main(a, b)
                {
                    return a + b;
                }
            """, [])

        with self.assertRaises(FunctionNotFound):
            yield self.fcalls.call("test_app", "test_bad_bind", [0, 1], gamespace=0, account=0)

    @gen_test(timeout=1)
    def test_parallel(self):
        """
        This test has timeout 1 because 4 calls (0.5s each) being called in parallel should be
        definitely done within one second
        """

        fn = yield self.functions.create_function(
            0, "test_parallel", """
                function main(args, api)
                {
                    var a = args[0];
                    var b = args[1];

                    api.sleep(0.5).done(function()
                    {
                        api.res(a + b);
                    });
                }
            """, [])

        yield self.functions.bind_function(0, "test_app", fn)

        prepared = yield self.fcalls.prepare(0, "test_app", "test_parallel")

        # call them in parallel
        res = yield [
            self.fcalls.call_fn(prepared, [1, 2]),
            self.fcalls.call_fn(prepared, [100, 200]),
            self.fcalls.call_fn(prepared, [-10, 10]),
            self.fcalls.call_fn(prepared, [100000, 200000])
        ]

        self.assertEqual(res, [3, 300, 0, 300000])

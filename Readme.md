# Exec Service

Every multiplayer projects needs to run the game code on the backend side.
<a href="https://github.com/anthill-platform/anthill-game">Game Service</a>
perfectly does that task. But sometimes you don't need that kind
of complicity and just to want a simple script that players can connect to
and do things here and there. In Javascript!

The service uses Git to host your code on, so you can setup a repository, put
your javascript there, configure it on the service, and you're all set.

## API

Please refer to the <a href="doc/API.md">API Documentation</a> for more information.

## Hello, world

```javascript
function hello_world(args) {
    return "Hello, world!";
}

hello_world.allow_call = true;
``` 

As simple at it looks like. Then you can call it from client library:

```rest
POST /call/test/1.0/hello_world
> Hello, world!
```

##### Simple, but secure

Only the functions that defined `allow_call = true` can be called by the client, thus declaring some functios
"API ready", others private.

## Sessions

Calling simple function is not always enough. Often the state between the calls has to be saved,
wrapping the whole call sequence in a "session". That's what the Sessions are for.

```javascript
function SessionHelloWorld(args)
{
    // this function is called upon session initialization
    this.name = "unknown";
}

SessionHelloWorld.allow_session = true;

SessionHelloWorld.prototype.my_name_is = function(args)
{
    this.name = args["name"];
    return "Gotcha!"
};

SessionHelloWorld.prototype.hello = function(args)
{
    return "Hello, " + this.name + "!";
};
```

Sessions are run by WebSockets, with <a href="http://www.jsonrpc.org/specification">JSON-RPC</a> as transport protocol.

```rest
WebSocket /session/test/1.0/SessionHelloWorld

call("hello")
> Hello, unknown!
call("my_name_is", {"name": "world"})
> Gotcha!
call("hello")
> Hello, world!
```

##### Cooler, still secure

Only constructor functions (`SessionHelloWorld` from example above) that define `allow_session = true` will be allowed to open session on.
Also, methods that start with underscore are not allowed to call:

```javascript
SessionHelloWorld.prototype._internal_method = function(args)
{
    return "I am so internal";
};
```

```rest
...

call("_internal_method")
Error 404: No such method
```
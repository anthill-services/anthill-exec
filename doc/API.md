
# Javascript support

EcmaScript 8 is supported.

## Plain Function definition

Plain functions can be defined as follows:

```javascript
function function_name(args)
{
    return "I am the result";
}
```
| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `args`           | JSON dictionary of arguments passed to the function                      |

## Throwing an error

To notify the client that error is happened during function/method call, this construction must be called:

```javascript
throw new Error(error_code, error_message)

// for example
throw new Error(404, "No such hero!")
```

## Asynchronous Functions

EcmaScript 8 states that functions can be defined as 
<a href="https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/async_function">asynchronous</a>.

The API allows that with the `async` / `await` keywords:

```javascript 1.8 
async function test(args)
{
    // wait for one second
    await sleep(1.0)
    // get the user profile
    var my_profile = await profile.get();
    return "Hello, " + my_profile.name;
}

test.prototype.allow_call = true;
````

```rest
POST /call/test/1.0/test
# waits for one, second, gets the profile
> Hello, %username%
```

# REST/WebSocket API

## Call the plain function

Calls the given function server-side, returning its result.

The function must have `allow_call = true` to be defined, otherwite the `404 Not Found`
will be returned. 

#### ← Request

```rest
POST /call/<game-name>/<game-version>/<function-name>
```

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `game-name`      | A name of the game to receive the config about                           |
| `game-version`   | Game version                                                             |
| `function-name`  | Name of the function to call                                             |
| `args`           | JSON dictionary of arguments that will be passed as `args` argument to the function |
| `access_token`   | A valid <a href="https://github.com/anthill-platform/anthill-login#access-tokens">Access Token</a> with `exec_func_call` permission.  |

#### → Response

Function response is returned as is.

| Response             | Description                                          |
|----------------------|------------------------------------------------------|
| `200 OK`             | Everything went OK, result follows.                  |
| `404 Not Found`      | No such function                                     |
| custom errors        | Function may throw errors with custom codes for the client application to process |

## Open a new Session

To open a new session, a new WebSocket connection on this location should be established:

#### WebSocket connection

```rest
/session/<game-name>/<game-version>/<class-name>
```

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `game-name`      | A name of the game to receive the config about                           |
| `game-version`   | Game version                                                             |
| `class-name`     | Name of the Construction Function to be used on this session                                             |
| `args`           | JSON dictionary of arguments that will be passed as `args` argument to the Construction Function |
| `access_token`   | A valid <a href="https://github.com/anthill-platform/anthill-login#access-tokens">Access Token</a> with `exec_func_call` permission.  |

For the session to be successfully be opened, a Constructor Function with name `class-name` should exists, and
should have `allow_session = true` to be defined:

```javascript
function Test(args) {}
Test.allow_session = true;
````

#### Communication protocol

<a href="http://www.jsonrpc.org/specification">JSON-RPC</a> is used as transport protocol to call the methods of the 
session, and get the responses.

##### Call a method

To call a method, a request named `call` should be sent.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `method_name`    | Name of method to be called.                                             |
| `arguments`      | JSON dictionary of arguments that will be passed as `args` argument to method |

Example of calling a method:
```
-> {"jsonrpc": "2.0", "method": "call", "params": {"method_name": "test", "arguments": {}}, "id": 1}
<- {"jsonrpc": "2.0", "result": "Testing!", "id": 1}
```

```javascript
function Test(args) {}

Test.prototype.test = function(args) {
    return "Testing!";
};

Test.allow_session = true;
````

Please note, that methods don't need `allow_call` since all public method of the Constructor function are
allowed to call. To make the method private, start its name with underscore.

#### `released` method

If the session needs to run some code once the connections is lost, a method `released` could be defined:

```javascript
Test.prototype.released = function(args) {
    log("I am being released");
};
```

It will be called automatically upon session being closed. This method cannot be called manually,
and should return no result, as it will be ignored. Also, this method allowed to be 
<a href="#asynchronous-functions">asynchronous</a>.

# Standard API

Along with standard Javascript functions, several are added by the API.

Please note that functions, marked with <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png"> are <a href="#asynchronous-functions">asynchronous</a>.
They return Promise that required to be `await`ed.

## `Error(code, message)`
See <a href="#throwing-an-error">Throwing an error</a>.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `code`           | The code indicating the problem. |
| `message`        | Error description |


## `log(message)`
To issue a log message, use `log(message)`

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `message`        | Log message |

## `sleep(delay)` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Delays the execution for some time.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `delay`          | Time for delay in seconds |

## web
An object to access to the internet

#### `web.get(url, [headers])` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Downloads the file at the `url` and returns its contents. 

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `url`            | An URI to download the contents from |
| `headers`        | (Optional). JSON object of HTTP headers to send |

## config
An object to access to the <a href="https://github.com/anthill-platform/anthill-config">Configuration Service</a>

#### `config.get()` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Returns the <a href="https://github.com/anthill-platform/anthill-config/blob/master/doc/API.md#get-the-configuration">Configuration Info</a> for the game name / game version.  

## store
An object to access to the <a href="https://github.com/anthill-platform/anthill-store">Store Service</a>

#### `store.get(name)` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Returns the configuration of the given Store

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `name`           | Store name |

#### `store.new_order(store, item, currency, amount, component)` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Places a new order in the Store. Returns the new order id.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `store`          | Store name |
| `item`           | Item name |
| `currency`       | Currency name |
| `amount`         | Items amount |
| `component`      | Component |

#### `store.update_order(order_id)` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Updates the given order. No additional documentation so far.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `order_id`       | Order id to update |

#### `store.update_orders()` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Updates all unfinished orders of the user. No additional documentation so far.

## profile
An object to access to the <a href="https://github.com/anthill-platform/anthill-profile">Profile Service</a>

#### `profile.get([path])` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Returns the user's profile.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `path`           | (Optional). Path of the profile to get. If not defined, the whole profile is returned |

#### `profile.update(profile, [path], [merge])` <img width="16" src="https://user-images.githubusercontent.com/1666014/32136810-72ccb840-bc1d-11e7-9934-7bc7fbc59913.png">
Updates the user's profile.

| Argument         | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `profile`        | A JSON object for the profile to update |
| `path`           | (Optional). Path of the profile to update. If not defined, the whole profile is updated |
| `merge`          | (Optional). If true (default), the JSON objects of existing profile and updated one are mixed, otherwise the old object is replaces |


## TO DO
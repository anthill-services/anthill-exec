
name = "stdlib.js"

source = """
V8Error = Error;

Error = function(code, message)
{
    V8Error.captureStackTrace(this, Error);
    
    this.code = code;
    this.message = message;
}
"""

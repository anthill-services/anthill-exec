(function(div, context)
{
    var controller = {
        ws: new ServiceJsonRPC(SERVICE, "stream_debug", context),

        log: function(message) {
            var zis = this;

            var node = $('<div>' + message + '</div>').appendTo(this.sandbox);

            setTimeout( function() {
                var height = zis.sandbox[0].scrollHeight;
                $(zis.sandbox).scrollTop(height)
            }, 250 );

            return node;
        },

        init: function (div, context) {
            var zis = this;

            this.account = context["account"];
            this.application_name = context["application_name"];
            this.application_version = context["application_version"];
            this.class_name = context["class_name"];
            this.commit = context["commit"];
            this.session_args = context["session_args"];
            this.messages = {};

            this.ws.handle("log", function (payload) {
                var message = payload["message"];

                zis.log(message);
            });
            this.ws.handle("inited", function (payload) {
                var result = payload["result"];

                zis.log('<span class="text text-success">' +
                    '<i class="fa fa-check" aria-hidden="true"></i> ' +
                    '<b>' + (result ? ('Initialized: ' + result + '.') : 'Initialized.') + '</b></span>');
            });

            this.ws.onerror = function (message) {
                console.log(message);
            };

            this.panel = $('<div class="panel panel-default"></div>').appendTo(div);
            this.header = $('<div class="panel-heading">' +
                '<div class="row">' +
                '<div class="col-sm-6">' +
                '<h3 class="panel-title padFix"><i class="fa fa-bars" aria-hidden="true"></i> Log</h3>' +
                '</div>' +
                '</div>' +
                '</div>').appendTo(this.panel);

            this.body = $('<div class="panel-body"></div>').appendTo(this.panel);

            this.sandbox = $('<pre class="output" style="height: 250px"></pre>').appendTo(this.body);
            this.input = $('<input type="text" class="form-control" ' +
                'placeholder="Type here to evaluate. You can use \'instance\' as a reference to the current' +
                ' object">').appendTo(this.body);

            this.input.keyup(function(event)
            {
                if(event.keyCode == 13)
                {
                    var text = zis.input.val();
                    if (text)
                    {
                        var _log = zis.log('<i class="fa fa-refresh fa-spin" aria-hidden="true"></i> ' +
                            '<b>Evaluating</b>: ' + text);

                        var _notify = notify_progress("Evaluating: " + text);

                        zis.ws.request("eval", {
                            "text": text
                        }).done(function (payload) {

                            var result = payload["result"];

                            _notify.close();
                            _log.html('<b>Evaluating</b>: ' + text);
                            zis.log('<i class="fa fa-check" aria-hidden="true"></i> ' +
                                JSON.stringify(result))
                        }).fail(function (code, message, data) {
                            _notify.close();
                            _log.html('<b>Evaluating</b>: ' + text);
                            notify_error("Error " + code + ": " + message);
                            zis.log('<i class="fa fa-exclamation-triangle" aria-hidden="true"></i> ' +
                                'Error: ' + code + ": " + message)
                        });

                        zis.input.val('');
                    }
                }
            });

            this.tabs_header = $('<ul class="nav nav-tabs" data-tabs="tabs">' +
                '<li><a href="#server_status" id="server_status_header" data-toggle="tab"></a></li>' +

                '<li class="active"><a href="#call_method" id="call_method_header" data-toggle="tab">' +
                '<i class="fa fa-play" aria-hidden="true"></i> Call a method</a></li>' +

                '</ul>').appendTo(div);

            this.tabs_content = $('<div class="tab-content">' +
                '<div class="tab-pane" id="server_status"></div>' +
                '</div>').appendTo(div);

            var call_method = $('<div class="tab-pane active" id="call_method"></div>').appendTo(this.tabs_content);

            render_node({
                "class": "form",
                "context": {},
                "methods": {
                    "post": {"style": "primary", "title": "Call"}
                },
                "fields": {
                    "method_name": {
                        "style": "primary", "validation": "non-empty", "type": "text", "value": "main",
                        "title": "Method Name", "order": 1
                    },
                    "arguments": {
                        "style": "primary", "validation": "non-empty", "type": "json", "value": {},
                        "title": "Method Arguments", "order": 4, "height": 100
                    }
                },
                "title": "Call a method",
                "callback": function (fields) {
                    try {
                        arguments = JSON.parse(fields["arguments"]);
                    }
                    catch (e) {
                        notify_error(e);
                        return false;
                    }

                    var method_name = fields["method_name"];

                    var _log = zis.log('<i class="fa fa-refresh fa-spin" aria-hidden="true"></i> ' +
                        '<b>Calling Method</b>: ' + method_name);

                    var _notify = notify_progress("Calling method: " + method_name);

                    zis.ws.request("call", {
                        "method_name": method_name,
                        "arguments": arguments
                    }).done(function (payload) {
                        _notify.close();
                        _log.remove();
                        notify_success("Method has been called!");
                        zis.log('<i class="fa fa-check" aria-hidden="true"></i> ' +
                            JSON.stringify(payload))
                    }).fail(function (code, message, data) {
                        _notify.close();
                        _log.remove();
                        notify_error("Error " + code + ": " + message);
                        zis.log('<i class="fa fa-exclamation-triangle" aria-hidden="true"></i> ' +
                            'Error: ' + code + ": " + message)
                    });

                    return false;
                }
            }, call_method);

            this.status('Connecting...', 'refresh', 'info');

            this.ws.onopen = function () {
                zis.status('Connected', 'check', 'success');
                zis.log('<i class="fa fa-refresh fa-spin fa-fw fa-loading" aria-hidden="true"></i> ' +
                    '<b>Connected, initializing...</b>');
            };

            this.ws.onclose = function (code, reason) {
                reason = reason || "Connection closed.";

                zis.status('Error ' + code + ": " + reason, 'times', 'danger');
                zis.log('<span class="text text-danger">' +
                    '<i class="fa fa-exclamation-triangle" aria-hidden="true"></i> ' +
                    '<b>Error ' + code + ": " + reason + '</b></span>');
            };
        },
        render_values: function (to, kv) {
            to.html('');
            var table = $('<table class="table"></table>').appendTo(to);

            for (var key in kv) {
                var value_obj = kv[key];

                var decorators = {
                    "label": function (value, agrs) {
                        return $('<span class="label label-' + agrs.color + '">' + value + '</span>');
                    },
                    "json": function (value, agrs) {
                        return new JSONFormatter(value, 0).render();
                    },
                    "icon": function (value, args) {
                        var node = $('<span></span>');

                        node.append('<i class="fa fa-' + args.icon + '" aria-hidden="true"></i> ' +
                            value);

                        return node;
                    }
                };

                var tr = $('<tr></tr>').appendTo(table);
                var property = $('<td class="col-sm-1 th-notop">' + value_obj.title + '</td>').appendTo(tr);
                var value = $('<td class="col-sm-3 th-notop"></td>').appendTo(tr);

                if (value_obj.decorator != null) {
                    var d = decorators[value_obj.decorator];

                    if (d != null) {
                        value.append(d(value_obj.value, value_obj.args))
                    }
                }
                else {
                    value.append(value_obj.value);
                }
            }
        },
        status: function (title, icon, color) {
            var server_status_header = $('#server_status_header');
            var server_status = $('#server_status');

            server_status_header.html(
                '<i class="fa fa-' + icon + ' text-' + color + '" aria-hidden="true"></i>' +
                ' Server status');

            this.render_values(server_status, [
                {
                    "title": "Connection status",
                    "value": title,
                    "decorator": "label",
                    "args": {
                        "color": color
                    }
                }
            ]);
        }
    };

    controller.init(div, context);
});

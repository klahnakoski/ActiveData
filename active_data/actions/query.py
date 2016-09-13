# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import flask
from flask import Response

from active_data import record_request
from pyLibrary import convert, strings
from pyLibrary.debugs.exceptions import Except
from pyLibrary.debugs.logs import Log
from pyLibrary.debugs.profiles import CProfiler
from pyLibrary.dot import coalesce, listwrap, join_field, split_field
from pyLibrary.env.files import File
from pyLibrary.maths import Math
from pyLibrary.queries import jx, meta, wrap_from
from pyLibrary.queries.containers import Container, STRUCT
from pyLibrary.queries.meta import TOO_OLD
from pyLibrary.strings import expand_template
from pyLibrary.thread.threads import Thread
from pyLibrary.times.dates import Date
from pyLibrary.times.durations import MINUTE
from pyLibrary.times.timer import Timer

from active_data.actions import save_query

BLANK = convert.unicode2utf8(File("active_data/public/error.html").read())
QUERY_SIZE_LIMIT = 10*1024*1024


def query(path):
    with CProfiler():
        try:
            with Timer("total duration") as query_timer:
                preamble_timer = Timer("preamble")
                with preamble_timer:
                    if flask.request.headers.get("content-length", "") in ["", "0"]:
                        # ASSUME A BROWSER HIT THIS POINT, SEND text/html RESPONSE BACK
                        return Response(
                            BLANK,
                            status=400,
                            headers={
                                "access-control-allow-origin": "*",
                                "content-type": "text/html"
                            }
                        )
                    elif int(flask.request.headers["content-length"]) > QUERY_SIZE_LIMIT:
                        Log.error("Query is too large")

                    request_body = flask.request.get_data().strip()
                    text = convert.utf82unicode(request_body)
                    text = replace_vars(text, flask.request.args)
                    data = convert.json2value(text)
                    record_request(flask.request, data, None, None)
                    if data.meta.testing:
                        _test_mode_wait(data)

                translate_timer = Timer("translate")
                with translate_timer:
                    frum = wrap_from(data['from'])
                    result = jx.run(data, frum=frum)

                    if isinstance(result, Container):  #TODO: REMOVE THIS CHECK, jx SHOULD ALWAYS RETURN Containers
                        result = result.format(data.format)

                save_timer = Timer("save")
                with save_timer:
                    if data.meta.save:
                        try:
                            result.meta.saved_as = save_query.query_finder.save(data)
                        except Exception:
                            pass


                result.meta.timing.preamble = Math.round(preamble_timer.duration.seconds, digits=4)
                result.meta.timing.translate = Math.round(translate_timer.duration.seconds, digits=4)
                result.meta.timing.save = Math.round(save_timer.duration.seconds, digits=4)
                result.meta.timing.total = "{{TOTAL_TIME}}"  # TIMING PLACEHOLDER

                with Timer("jsonification") as json_timer:
                    response_data = convert.unicode2utf8(convert.value2json(result))

            with Timer("post timer"):
                # IMPORTANT: WE WANT TO TIME OF THE JSON SERIALIZATION, AND HAVE IT IN THE JSON ITSELF.
                # WE CHEAT BY DOING A (HOPEFULLY FAST) STRING REPLACEMENT AT THE VERY END
                timing_replacement = b'"total": ' + str(Math.round(query_timer.duration.seconds, digits=4)) +\
                                     b', "jsonification": ' + str(Math.round(json_timer.duration.seconds, digits=4))
                response_data = response_data.replace(b'"total": "{{TOTAL_TIME}}"', timing_replacement)
                Log.note("Response is {{num}} bytes in {{duration}}", num=len(response_data), duration=query_timer.duration)

                return Response(
                    response_data,
                    status=200,
                    headers={
                        "access-control-allow-origin": "*",
                        "content-type": result.meta.content_type
                    }
                )
        except Exception, e:
            e = Except.wrap(e)
            return _send_error(query_timer, request_body, e)


def _test_mode_wait(query):
    """
    WAIT FOR METADATA TO ARRIVE ON INDEX
    :param query: dict() OF REQUEST BODY
    :return: nothing
    """

    m = meta.singlton
    now = Date.now()
    end_time = now + MINUTE

    # MARK COLUMNS DIRTY
    m.meta.columns.update({
        "clear": [
            "partitions",
            "count",
            "cardinality",
            "last_updated"
        ],
        "where": {"eq": {"table": join_field(split_field(query["from"])[0:1])}}
    })

    # BE SURE THEY ARE ON THE todo QUEUE FOR RE-EVALUATION
    cols = [c for c in m.get_columns(table_name=query["from"]) if c.type not in STRUCT]
    for c in cols:
        Log.note("Mark {{column}} dirty at {{time}}", column=c.name, time=now)
        c.last_updated = now - TOO_OLD
        m.todo.push(c)

    while end_time > now:
        # GET FRESH VERSIONS
        cols = [c for c in m.get_columns(table_name=query["from"]) if c.type not in STRUCT]
        for c in cols:
            if not c.last_updated or c.cardinality == None :
                Log.note(
                    "wait for column (table={{col.table}}, name={{col.name}}) metadata to arrive",
                    col=c
                )
                break
        else:
            break
        Thread.sleep(seconds=1)
    for c in cols:
        Log.note(
            "fresh column name={{column.name}} updated={{column.last_updated|date}} parts={{column.partitions}}",
            column=c
        )


def _send_error(active_data_timer, body, e):
    record_request(flask.request, None, body, e)
    Log.warning("Could not process\n{{body}}", body=body.decode("latin1"), cause=e)
    e = e.as_dict()
    e.meta.timing.total = active_data_timer.duration.seconds

    # REMOVE TRACES, BECAUSE NICER TO HUMANS
    # def remove_trace(e):
    #     e.trace = e.trace[0:1:]
    #     for c in listwrap(e.cause):
    #         remove_trace(c)
    # remove_trace(e)

    return Response(
        convert.unicode2utf8(convert.value2json(e)),
        status=400,
        headers={
            "access-control-allow-origin": "*",
            "content-type": "application/json"
        }
    )


def replace_vars(text, params=None):
    """
    REPLACE {{vars}} WITH ENVIRONMENTAL VALUES
    """
    start = 0
    var = strings.between(text, "\"{{", "}}\"", start)
    while var:
        replace = "\"{{" + var + "}}\""
        index = text.find(replace, 0)
        end = index + len(replace)

        try:
            replacement = unicode(Date(var).unix)
            text = text[:index] + replacement + text[end:]
            start = index + len(replacement)
        except Exception, _:
            start += 1

        var = strings.between(text, "{{", "}}", start)

    text = expand_template(text, coalesce(params, {}))
    return text

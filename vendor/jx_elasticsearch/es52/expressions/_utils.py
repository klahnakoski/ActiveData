# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import absolute_import, division, unicode_literals

from jx_base.expressions import (
    FALSE,
    Variable as Variable_)
from jx_base.expressions.literal import is_literal, TRUE
from jx_base.language import Language, is_op
from jx_elasticsearch.es52.painless import Painless
from jx_elasticsearch.es52.painless.es_script import es_script
from mo_dots import Null, to_data
from mo_future import first
from mo_logs import Log
from mo_math import MAX

MATCH_NONE, MATCH_ALL, Painlesss, AndOp, OrOp = [None] * 5  # IMPORTS


def _inequality_to_esfilter(self, schema):
    if is_op(self.lhs, Variable_) and is_literal(self.rhs):
        cols = schema.leaves(self.lhs.var)
        if not cols:
            lhs = self.lhs.var  # HAPPENS DURING DEBUGGING, AND MAYBE IN REAL LIFE TOO
        elif len(cols) == 1:
            lhs = first(cols).es_column
        else:
            raise Log.error("operator {{op|quote}} does not work on objects", op=self.op)
        return {"range": {lhs: {self.op: self.rhs.value}}}
    else:
        script = Painless[self].to_es_script(schema)
        if script.miss is not FALSE:
            Log.error("inequality must be decisive")
        return {"script": es_script(script.expr)}


def split_expression_by_depth(where, schema, output=None, var_to_depth=None):
    """
    :param where: EXPRESSION TO INSPECT
    :param schema: THE SCHEMA
    :param output:
    :param var_to_depth: MAP FROM EACH VARIABLE NAME TO THE DEPTH
    :return:
    """
    """
    It is unfortunate that ES can not handle expressions that
    span nested indexes.  This will split your where clause
    returning {"and": [filter_depth0, filter_depth1, ...]}
    """
    vars_ = where.vars()

    if var_to_depth is None:
        if not vars_:
            return Null
        # MAP VARIABLE NAMES TO HOW DEEP THEY ARE
        var_to_depth = {
            v.var: max(len(c.nested_path) - 1, 0) for v in vars_ for c in schema[v.var]
        }
        all_depths = set(var_to_depth.values())
        if len(all_depths) == 0:
            all_depths = {0}
        output = to_data([[] for _ in range(MAX(all_depths) + 1)])
    else:
        all_depths = set(var_to_depth[v.var] for v in vars_)

    if len(all_depths) == 1:
        output[first(all_depths)] += [where]
    elif is_op(where, AndOp):
        for a in where.terms:
            split_expression_by_depth(a, schema, output, var_to_depth)
    else:
        Log.error("Can not handle complex where clause")

    return output


def split_expression_by_path(
    expr, schema, lang=Language
):
    """
    :param expr: EXPRESSION TO INSPECT
    :param schema: THE SCHEMA
    :param output: THE MAP FROM PATH TO EXPRESSION WE WANT UPDATED
    :param var_to_columns: MAP FROM EACH VARIABLE NAME TO THE DEPTH
    :return: type, output: (OP, MAP) PAIR WHERE OP IS OPERATOR TO APPLY ON MAP ITEMS, AND MAP FROM PATH TO EXPRESSION
    """
    if is_op(expr, AndOp):
        if not expr.terms:
            return AndOp, {".": TRUE}
        elif len(expr.terms) == 1:
            return split_expression_by_path(expr.terms[0], schema, lang=lang)

        output = {}
        for w in expr.terms:
            mode, split = split_expression_by_path(w, schema, lang=lang)
            if mode == AndOp:
                for v, es in split.items():
                    ae = output.get(v)
                    if not ae:
                        output[v] = ae = AndOp([])
                    ae.terms.append(es)
            else:
                Log.error("confused")
        return AndOp, output

    expr_vars = expr.vars()
    var_to_columns = {v.var: schema.values(v.var) for v in expr_vars}
    all_paths = set(c.nested_path[0] for v in expr_vars for c in var_to_columns[v.var])

    if len(all_paths) == 0:
        return AndOp, {'.': expr}  # CONSTANTS
    elif len(all_paths) == 1:
        return AndOp, {first(all_paths): expr}
    else:
        exprs = [expr]
        for v, cols in var_to_columns.items():
            for col in cols:
                var_to_columns[col.es_column] = [col]
            if len(cols) <= 1:
                continue

            more_expr = []
            for e in exprs:
                for col in cols:
                    more_expr.append(e.map({v: col.es_column}))
            exprs = more_expr

        acc = {}
        for e in exprs:
            nestings = list(set(c.nested_path[0] for v in e.vars() for c in var_to_columns[v]))
            if not nestings:
                a = acc.get('.')
                if not a:
                    acc['.'] = a = OrOp([])
                a.terms.append(e)
            elif len(nestings) == 1:
                a = acc.get(nestings[0])
                if not a:
                    acc[nestings[0]] = a = OrOp([])
                a.terms.append(e)
            else:
                Log.error("Expression is too complex")

        return OrOp, acc


def get_type(var_name):
    type_ = var_name.split(".$")[1:]
    if not type_:
        return "j"
    return json_type_to_es_script_type.get(type_[0], "j")


json_type_to_es_script_type = {"string": "s", "boolean": "b", "number": "n"}


ES52 = Language("ES52")

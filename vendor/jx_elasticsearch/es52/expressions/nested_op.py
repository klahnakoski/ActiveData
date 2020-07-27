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

from jx_base.expressions import NestedOp as _NestedOp, NULL
from jx_elasticsearch.es52.expressions.utils import ES52
from mo_imports import export


class NestedOp(_NestedOp):
    def to_es(self, schema):
        if self.path.var == ".":
            return ES52[self.select].to_es() | {"query": ES52[self.where].to_es(schema), "from": 0}
        elif bool(self.select) and self.select is not NULL:
            return {
                "nested": {
                    "path": self.path.var,
                    "query": ES52[self.where].to_es(schema),
                    "inner_hits": (ES52[self.select].to_es() | {"size": 100000})
                }
            }
        else:
            return {
                "nested": {
                    "path": self.path.var,
                    "query": ES52[self.where].to_es(schema)
                }
            }


export("jx_elasticsearch.es52.expressions.utils", NestedOp)
export("jx_elasticsearch.es52.expressions.eq_op", NestedOp)

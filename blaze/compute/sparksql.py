from __future__ import absolute_import, division, print_function


import sqlalchemy as sa
import itertools
from ..data.sql import dshape_to_alchemy
from ..dispatch import dispatch
from ..expr import (Expr, TableSymbol, Column, Projection, By, Join, Sort, Head,
Label, ReLabel, Reduction, BinOp, UnaryOp, any, all, sum, max ,min, var, std,
count, nunique, mean, Selection, Apply, Distinct, RowWise)
from ..sparksql import *

from pyspark.sql import SchemaRDD
import pyspark


names = ('_table_%d' % i for i in itertools.count(1))

class SparkSQLQuery(object):
    """ Pair of PySpark SQLContext and SQLAlchemy Table

    Python's SparkSQL interface only accepts strings.  We use SQLAlchemy to
    generate these strings.  To do this we'll have to pass around a pair of
    (SQLContext, sqlalchemy.Selectable)
    """
    __slots__ = 'context', 'query', 'mapping'

    def __init__(self, context, query, mapping):
        self.context = context
        self.query = query
        self.mapping = mapping



def make_query(rdd, primary_key='', name=None):
    # SparkSQL
    name = name or next(names)
    context = rdd.sql_ctx
    context.registerRDDAsTable(rdd, name)

    # SQLAlchemy
    schema = discover(rdd).subshape[0]
    columns = dshape_to_alchemy(schema)
    for column in columns:
        if column.name == primary_key:
            column.primary_key = True

    metadata = sa.MetaData()  # TODO: sync this between many tables

    query = sa.Table(name, metadata, *columns)

    mapping = {rdd: query}

    return SparkSQLQuery(context, query, mapping)


@dispatch((UnaryOp, Expr), SparkSQLQuery)
def compute_one(expr, q, **kwargs):
    scope = kwargs.pop('scope', dict())
    scope = {t: q.mapping.get(data, data) for t, data in scope.items()}

    q2 = compute_one(expr, q.query, scope=scope, **kwargs)
    return SparkSQLQuery(q.context, q2, q.mapping)


@dispatch((BinOp, Expr), SparkSQLQuery, SparkSQLQuery)
def compute_one(expr, a, b, **kwargs):
    assert a.context == b.context

    mapping = toolz.merge(a.mapping, b.mapping)

    scope = kwargs.pop('scope', dict())
    scope = {t: mapping.get(data, data) for t, data in scope.items()}

    c = compute_one(expr, a.query, b.query, scope=scope, **kwargs)
    return SparkSQLQuery(a.context, c, mapping)


@dispatch(TableSymbol, SchemaRDD)
def compute_one(ts, rdd, **kwargs):
    return make_query(rdd)


@dispatch((var, Label, std, Sort, count, nunique, Selection, mean,
           Head, ReLabel, Apply, Distinct, RowWise, By, any, all, sum, max,
           min, Reduction, Projection, Column), SchemaRDD)
def compute_one(e, rdd, **kwargs):
    return compute_one(e, make_query(rdd), **kwargs)



from .sql import select
def sql_string(query):
    return str(select(query)).replace('\n', ' ')

@dispatch(Expr, SparkSQLQuery, dict)
def post_compute(expr, query, d):
    result = query.context.sql(sql_string(query.query))
    if isinstance(expr, TableExpr) and expr.iscolumn:
        result = result.map(lambda x: x[0])
    return result

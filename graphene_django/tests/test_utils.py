import pytest

import graphene
from django.utils.translation import gettext_lazy

from ..utils import camelize, get_model_fields, merge_schema
from ..types import DjangoObjectType
from ..registry import reset_global_registry
from .models import Film, Reporter


@pytest.fixture(scope='function', autouse=True)
def clear_global_registry():
    yield
    reset_global_registry()


def test_get_model_fields_no_duplication():
    reporter_fields = get_model_fields(Reporter)
    reporter_name_set = set([field[0] for field in reporter_fields])
    assert len(reporter_fields) == len(reporter_name_set)

    film_fields = get_model_fields(Film)
    film_name_set = set([field[0] for field in film_fields])
    assert len(film_fields) == len(film_name_set)


def test_camelize():
    assert camelize({}) == {}
    assert camelize("value_a") == "value_a"
    assert camelize({"value_a": "value_b"}) == {"valueA": "value_b"}
    assert camelize({"value_a": ["value_b"]}) == {"valueA": ["value_b"]}
    assert camelize({"value_a": ["value_b"]}) == {"valueA": ["value_b"]}
    assert camelize({"nested_field": {"value_a": ["error"], "value_b": ["error"]}}) == {
        "nestedField": {"valueA": ["error"], "valueB": ["error"]}
    }
    assert camelize({"value_a": gettext_lazy("value_b")}) == {"valueA": "value_b"}
    assert camelize({"value_a": [gettext_lazy("value_b")]}) == {"valueA": ["value_b"]}
    assert camelize(gettext_lazy("value_a")) == "value_a"
    assert camelize({gettext_lazy("value_a"): gettext_lazy("value_b")}) == {
        "valueA": "value_b"
    }
    assert camelize({0: {"field_a": ["errors"]}}) == {0: {"fieldA": ["errors"]}}


def test_merge_schema():
    class S:
        def __init__(self, q, m=None, s=None):
            self.Query = q
            self.Mutation = m
            self.Subscription = s

    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()

    class Q0(object):
        films = FilmType.Connection()

    class M0(object):
        update = graphene.Int()

    class S0(object):
        subsc = graphene.Int()

    class Q1(object):
        reporters = ReporterType.Connection()

    schema0 = S(Q0, M0, S0)
    schema1 = S(Q1)

    Query, Mutation, Subscription = merge_schema(schema0, schema1)
    schema = graphene.Schema(
        query=Query,
        mutation=Mutation,
        subscription=Subscription
    )
    assert hasattr(schema._query, 'films')
    assert hasattr(schema._query, 'reporters')
        

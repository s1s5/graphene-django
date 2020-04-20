import inspect

import six
from django.conf import settings
from django.db import models
from django.db.models.manager import Manager
from django.utils.encoding import force_str
from django.utils.functional import Promise

import graphene
from graphene.utils.str_converters import to_camel_case
from graphene_django.debug import DjangoDebug

try:
    import django_filters  # noqa

    DJANGO_FILTER_INSTALLED = True
except ImportError:   # pragma: no cover
    DJANGO_FILTER_INSTALLED = False


def isiterable(value):
    try:
        iter(value)
    except TypeError:   # pragma: no cover
        return False
    return True


def _camelize_django_str(s):
    if isinstance(s, Promise):
        s = force_str(s)
    return to_camel_case(s) if isinstance(s, six.string_types) else s


def camelize(data):
    if isinstance(data, dict):
        return {_camelize_django_str(k): camelize(v) for k, v in data.items()}
    if isiterable(data) and not isinstance(data, (six.string_types, Promise)):
        return [camelize(d) for d in data]
    return data


def get_reverse_fields(model, local_field_names):
    for name, attr in model.__dict__.items():
        # Don't duplicate any local fields
        if name in local_field_names:
            continue

        # "rel" for FK and M2M relations and "related" for O2O Relations
        related = getattr(attr, "rel", None) or getattr(attr, "related", None)
        if isinstance(related, models.ManyToOneRel):
            yield (name, related)
        elif isinstance(related, models.ManyToManyRel) and not related.symmetrical:
            yield (name, related)


def maybe_queryset(value):
    if isinstance(value, Manager):
        value = value.get_queryset()
    return value


def get_model_fields(model):
    local_fields = [
        (field.name, field)
        for field in sorted(
            list(model._meta.fields) + list(model._meta.local_many_to_many)
        )
    ]

    # Make sure we don't duplicate local fields with "reverse" version
    local_field_names = [field[0] for field in local_fields]
    reverse_fields = get_reverse_fields(model, local_field_names)

    all_fields = local_fields + list(reverse_fields)

    return all_fields


def is_valid_django_model(model):
    return inspect.isclass(model) and issubclass(model, models.Model)


def import_single_dispatch():
    try:
        from functools import singledispatch
    except ImportError:   # pragma: no cover
        singledispatch = None

    if not singledispatch:   # pragma: no cover
        try:
            from singledispatch import singledispatch
        except ImportError:
            pass

    if not singledispatch:   # pragma: no cover
        raise Exception(
            "It seems your python version does not include "
            "functools.singledispatch. Please install the 'singledispatch' "
            "package. More information here: "
            "https://pypi.python.org/pypi/singledispatch"
        )

    return singledispatch


def check_attrs_override(types):
    keys = set()
    for t in types:
        k = set(x for x in dir(t) if not (
            x.startswith('__') and x.endswith('__')))
        if keys & k:
            raise Exception('{} found same key'.format(keys & k))
        keys.update(k)


def merge_schema(*schemas):
    queries, mutations, subscriptions = [], [], []
    for schema in schemas:
        queries.append(getattr(schema, 'Query', None))
        mutations.append(getattr(schema, 'Mutation', None))
        subscriptions.append(getattr(schema, 'Subscription', None))
    queries = [x for x in queries if x] + [graphene.ObjectType]
    mutations = [x for x in mutations if x] + [graphene.ObjectType]
    subscriptions = [x for x in subscriptions if x] + [graphene.ObjectType]

    check_attrs_override(queries[:-1])
    check_attrs_override(mutations[:-1])
    check_attrs_override(subscriptions[:-1])

    query_attrs = {}

    if settings.DEBUG:
        query_attrs['debug'] = graphene.Field(DjangoDebug, name='_debug')

    return (
        type('Query', tuple(queries), query_attrs),
        type('Mutation', tuple(mutations), {}),
        type('Subscription', tuple(subscriptions), {}),
    )

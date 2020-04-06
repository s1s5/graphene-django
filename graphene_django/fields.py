from functools import partial
import logging

import six
from django.db.models.query import QuerySet
from django.db.models import Q

from graphql_relay.connection.arrayconnection import connection_from_list_slice
from promise import Promise

from graphene import NonNull
from graphene.relay import ConnectionField, PageInfo
from graphene.types import Field, List

from .settings import graphene_settings
from .utils import maybe_queryset

logger = logging.getLogger(__name__)


class DjangoListField(Field):
    def __init__(self, _type, *args, **kwargs):
        from .types import DjangoObjectType

        if isinstance(_type, NonNull):
            _type = _type.of_type

        # Django would never return a Set of None  vvvvvvv
        super(DjangoListField, self).__init__(List(NonNull(_type)), *args, **kwargs)

        assert issubclass(
            self._underlying_type, DjangoObjectType
        ), "DjangoListField only accepts DjangoObjectType types"

    @property
    def _underlying_type(self):
        _type = self._type
        while hasattr(_type, "of_type"):
            _type = _type.of_type
        return _type

    @property
    def model(self):
        return self._underlying_type._meta.model

    @staticmethod
    def list_resolver(django_object_type, resolver, root, info, **args):
        queryset = maybe_queryset(resolver(root, info, **args))
        if queryset is None:
            # Default to Django Model queryset
            # N.B. This happens if DjangoListField is used in the top level Query object
            model_manager = django_object_type._meta.model.objects
            queryset = maybe_queryset(
                django_object_type.get_queryset(model_manager, info)
            )
        return queryset

    def get_resolver(self, parent_resolver):
        _type = self.type
        if isinstance(_type, NonNull):
            _type = _type.of_type
        django_object_type = _type.of_type.of_type
        return partial(self.list_resolver, django_object_type, parent_resolver)


class DjangoConnectionField(ConnectionField):
    def __init__(self, *args, **kwargs):
        self.on = kwargs.pop("on", False)
        self.max_limit = kwargs.pop(
            "max_limit", graphene_settings.RELAY_CONNECTION_MAX_LIMIT
        )
        self.enforce_first_or_last = kwargs.pop(
            "enforce_first_or_last",
            graphene_settings.RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST,
        )
        super(DjangoConnectionField, self).__init__(*args, **kwargs)

    @property
    def type(self):
        from .types import DjangoObjectType

        _type = super(ConnectionField, self).type
        non_null = False
        if isinstance(_type, NonNull):
            _type = _type.of_type
            non_null = True
        assert issubclass(
            _type, DjangoObjectType
        ), "DjangoConnectionField only accepts DjangoObjectType types"
        assert _type._meta.connection, "The type {} doesn't have a connection".format(
            _type.__name__
        )
        connection_type = _type._meta.connection
        if non_null:
            return NonNull(connection_type)
        return connection_type

    @property
    def connection_type(self):
        type = self.type
        if isinstance(type, NonNull):
            return type.of_type
        return type

    @property
    def node_type(self):
        return self.connection_type._meta.node

    @property
    def model(self):
        return self.node_type._meta.model

    def get_manager(self):
        if self.on:
            return getattr(self.model, self.on)
        else:
            return self.model._default_manager

    @classmethod
    def resolve_queryset(cls, connection, queryset, info, args):
        # queryset is the resolved iterable from ObjectType
        return connection._meta.node.get_queryset(queryset, info)

    @classmethod
    def instance_to_cursor(cls, instance):
        if instance:
            try:
                return hex(instance.pk)
            except:
                pass

    @classmethod
    def cursor_to_instance(cls, cursor, model_type):
        if cursor:
            return model_type._default_manager.get(pk=int(cursor, 16))

    @classmethod
    def split_query(cls, queryset, order_by, instance):
        sumq, q = None, None
        for order in order_by:
            if order.startswith('-'):
                field = order[1:]
                expr = '{}__gt'.format(field)
            else:
                field = order
                expr = '{}__lt'.format(field)
            o = getattr(instance, field)
            if q is None:
                cq = Q(**{expr: o})
                q = Q(field=o)
                sumq = cq
            else:
                # queryset = queryset.filter(q and Q(**{expr: cond[order]}))
                cq = q and Q(**{expr: o})
                q = q and Q(field=o)
                sumq = sumq or cq
        return queryset.filter(sumq), queryset.exclude(sumq)

    @classmethod
    def connection_from_queryset(cls, queryset, args, connection_type,
                                 edge_type, pageinfo_type):
        if 'order_by' in args and args['order_by']:  # TODO: order_byは固定・・・
            order_by = args['order_by'].split(',')
        else:
            assert hasattr(queryset.model._meta, 'ordering'), 'must specify order_by or ordering in models'
            order_by = queryset.model._meta.ordering
        model_type = connection_type._meta.node._meta.model

        args = args or {}

        before = cls.cursor_to_instance(args.get('before'), model_type)
        after = cls.cursor_to_instance(args.get('after'), model_type)
        first = args.get('first')
        last = args.get('last')

        has_next_page, has_previous_page = False, False
        if before:
            queryset, qs_ex = cls.split_query(queryset, order_by, before)
            has_next_page = qs_ex.exists()

        if after:
            qs_ex, queryset = cls.split_query(queryset, order_by, after)
            has_previous_page = qs_ex.exists()

        if isinstance(first, int):
            has_next_page = queryset[first:].exists()
            queryset = queryset[:first]

        if isinstance(last, int):
            logger.warning('performance warning queryset.count called')
            index = max(0, queryset.count() - last)
            has_next_page = queryset[:index].exists()
            queryset = queryset[index:]

        edges = [
            edge_type(
                node=node,
                cursor=cls.instance_to_cursor(node)
            )
            for node in queryset
        ]

        first_edge_cursor = edges[0].cursor if edges else None
        last_edge_cursor = edges[-1].cursor if edges else None

        return connection_type(
            edges=edges,
            page_info=pageinfo_type(
                start_cursor=first_edge_cursor,
                end_cursor=last_edge_cursor,
                has_previous_page=has_previous_page,
                has_next_page=has_next_page,
            )
        )

    @classmethod
    def resolve_connection(cls, connection, args, iterable):
        try:
            if isinstance(iterable, list):
                # DataLoader使うとこっちが呼ばれる
                _len = len(iterable)
                return connection_from_list_slice(
                    iterable,
                    args,
                    slice_start=0,
                    list_length=_len,
                    list_slice_length=_len,
                    connection_type=connection,
                    edge_type=connection.Edge,
                    pageinfo_type=PageInfo)

            iterable = maybe_queryset(iterable)
            return cls.connection_from_queryset(
                iterable, args,
                connection_type=connection,
                edge_type=connection.Edge,
                pageinfo_type=PageInfo)
        except Exception as e:
            logger.exception(e)
            raise

    @classmethod
    def connection_resolver(
        cls,
        resolver,
        connection,
        default_manager,
        queryset_resolver,
        max_limit,
        enforce_first_or_last,
        root,
        info,
        **args
    ):
        first = args.get("first")
        last = args.get("last")

        if enforce_first_or_last:
            assert first or last, (
                "You must provide a `first` or `last` value to properly paginate the `{}` connection."
            ).format(info.field_name)

        if max_limit:
            if first:
                assert first <= max_limit, (
                    "Requesting {} records on the `{}` connection exceeds the `first` limit of {} records."
                ).format(first, info.field_name, max_limit)
                args["first"] = min(first, max_limit)

            if last:
                assert last <= max_limit, (
                    "Requesting {} records on the `{}` connection exceeds the `last` limit of {} records."
                ).format(last, info.field_name, max_limit)
                args["last"] = min(last, max_limit)

            if not (first or last):
                assert False, (
                    "set max_limit({}) without first({}) or last({})"
                ).format(max_limit, first, last)

        # eventually leads to DjangoObjectType's get_queryset (accepts queryset)
        # or a resolve_foo (does not accept queryset)
        iterable = resolver(root, info, **args)
        if iterable is None:
            iterable = default_manager
        # thus the iterable gets refiltered by resolve_queryset
        # but iterable might be promise
        iterable = queryset_resolver(connection, iterable, info, args)
        on_resolve = partial(cls.resolve_connection, connection, args)

        if Promise.is_thenable(iterable):
            return Promise.resolve(iterable).then(on_resolve)

        return on_resolve(iterable)

    def get_resolver(self, parent_resolver):
        return partial(
            self.connection_resolver,
            parent_resolver,
            self.connection_type,
            self.get_manager(),
            self.get_queryset_resolver(),
            self.max_limit,
            self.enforce_first_or_last,
        )

    def get_queryset_resolver(self):
        return self.resolve_queryset

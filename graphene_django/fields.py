from functools import partial
import logging

import six
from django.db.models.query import QuerySet
from django.db.models import Q
from django.db.models.manager import Manager
from django.db.models.fields.related_descriptors import (
    ForeignKeyDeferredAttribute, ForwardManyToOneDescriptor,
    ForwardOneToOneDescriptor, ManyToManyDescriptor,
    ReverseManyToOneDescriptor, ReverseOneToOneDescriptor,
)


from graphql_relay.connection.arrayconnection import connection_from_list_slice
from promise import Promise

from graphene import NonNull
from graphene.relay import ConnectionField, PageInfo, Node
from graphene.types import Field, List

from .registry import get_global_registry
from .settings import graphene_settings
from .utils import maybe_queryset

logger = logging.getLogger(__name__)


class DefaultDjangoField(Field):
    def __init__(self, _type, *args, **kwargs):
        self._model = _type._meta.model
        registry = get_global_registry()
        self._type = registry.get_type_for_model(self._model)
        self.__get_from_parent = getattr(self._type, 'get_from_parent', self._get_from_parent)
        self.__resolve = getattr(self._type, 'resolve', lambda resolved, *args, **kwargs : resolved)
        super().__init__(_type, *args, resolver=self._resolve, **kwargs)

    def _get_from_parent(self, parent, info):
        return getattr(parent, info.field_name, None)

    def _resolve(self, parent, info):
        return self.__resolve(self.__get_from_parent(parent, info), parent, info)

    def resolve_id(self, parent_resolver, parent, info, id=None, *args, **kwargs):
        if id is None:
            resolved = parent_resolver(parent, info, *args, **kwargs)
        else:
            resolved = Node.get_node_from_global_id(info, id)
        return self.__resolve(resolved, parent, info)

    def get_resolver(self, parent_resolver):
        return partial(self.resolve_id, parent_resolver)


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
    def _get_related_model(cls, field):
        if isinstance(field, ForwardManyToOneDescriptor):
            return True, field.field.related_model
        elif isinstance(field, ReverseOneToOneDescriptor):
            return True, field.related.related_model
        elif isinstance(field, ManyToManyDescriptor):
            return False, field.rel.related_model if field.reverse else field.field.related_model
        elif isinstance(field, ReverseManyToOneDescriptor):
            return False, field.rel.related_model
        return None, None

    @classmethod
    def _search_related(cls, field_ast, model, prefix=None, prefix_bool=True):
        # print(field_ast, model)
        def find_edges(field):
            if not field:
                return
            for j in field.selection_set.selections:
                # print(dir(j.name), type(j.name))
                if j.name.value == 'edges':
                    return j

        def find_node(field):
            if not field:
                return
            for j in field.selection_set.selections:
                if j.name.value == 'node':
                    return j

        def find_field(field):
            ll = []
            if not field:
                return []
            for name, cur_ast in [(j.name.value, j) for j in field.selection_set.selections]:
                if name == 'edges':
                    continue
                attr = getattr(model, name, None)
                # print("=" * 30, prefix, name, "=" * 30, )
                # print(name, attr, dir(attr), type(attr.field), getattr(attr.field, 'rel_class', None), getattr(attr, 'get_queryset', None))
                # print(isinstance(attr, ForeignKeyDeferredAttribute))
                # print(isinstance(attr, ForwardManyToOneDescriptor))
                # print(isinstance(attr, ForwardOneToOneDescriptor))
                # print(isinstance(attr, ManyToManyDescriptor))
                # print(isinstance(attr, ReverseManyToOneDescriptor))
                # print(isinstance(attr, ReverseOneToOneDescriptor))
                # print(name, attr, dir(attr), dir(getattr(attr, 'rel', None)))
                f, m = cls._get_related_model(attr)
                if m:
                    ll.append((f, name))
                    ll += cls._search_related(cur_ast, m, name, prefix_bool and f)
                # if isinstance(attr, (ForwardManyToOneDescriptor, ReverseOneToOneDescriptor)):
                #     ll.append((True, name))
                #     # print("recursive search : ", name)
                #     # print(cur_ast)
                #     # print(cls._get_related_model(attr))
                #     ll += cls._search_related(cur_ast, cls._get_related_model(attr), name, prefix_bool)
                # elif isinstance(attr, (ReverseManyToOneDescriptor, )):
                #     ll.append((False, name))
                #     # print("recursive search : ", name)
                #     # print(cur_ast)
                #     # print(cls._get_related_model(attr))
                #     ll += cls._search_related(cur_ast, cls._get_related_model(attr), name, False)
            return ll

        related = []
        related += find_field(field_ast)
        related += find_field(find_node(find_edges(field_ast)))
        if prefix:
            related = [(x[0] and prefix_bool, '{}__{}'.format(prefix, x[1])) for x in related]
        # print("related => ", related)
        return related


    @classmethod
    def optimize_queryset(cls, connection, queryset, info, args):
        if not isinstance(queryset, Manager):
            return queryset

        related = []
        for ast in info.field_asts:
            related += cls._search_related(ast, queryset.model)

        attached = set()
        
        for b, name in related:
            if name in attached:
                continue
            # print(name, related, issubclass(related, (ManyToOneRel, )), issubclass(related, (ManyToManyRel, )))
            attached.add(name)
            # print(name, '=>', b)
            if b:
                queryset = queryset.select_related(name)
            else:
                queryset = queryset.prefetch_related(name)
        return queryset

    @classmethod
    def resolve_queryset(cls, connection, queryset, info, args):
        # print("resolve queryset : ", cls, queryset)
        # queryset is the resolved iterable from ObjectType
        # queryset = cls.optimize_queryset(connection, queryset, info, args)
        return connection._meta.node.get_queryset(queryset, info)

    @classmethod
    def get_before_and_after_cursor(cls, order_by, instance):
        queryset = instance._meta.model.objects.order_by(*order_by).all()
        qs_before, qs_after = cls.split_query(queryset, order_by, instance)

        if qs_before.exists():
            before = cls.instance_to_cursor(qs_before.reverse()[0])
        else:
            before = None

        if qs_after.exists():
            after = cls.instance_to_cursor(qs_after[0])
        else:
            after = None

        return before, after

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
            if o is None:
                continue  # TODO: これでいいのか・・・？
            if q is None:
                cq = Q(**{expr: o})
                q = Q(**{field: o})
                sumq = cq
            else:
                cq = q & Q(**{expr: o})
                q = q & Q(**{field: o})
                sumq = sumq | cq
        return queryset.filter(sumq), queryset.exclude(sumq).exclude(pk=instance.pk)

    @classmethod
    def connection_from_queryset(cls, queryset, args, connection_type,
                                 edge_type, pageinfo_type):
        if 'order_by' in args and args['order_by']:  # TODO: order_byは固定・・・
            if isinstance(args['order_by'], str):
                order_by = args['order_by'].split(',')
            else:
                order_by = args['order_by']
        elif getattr(queryset.model._meta, 'ordering', None):
            order_by = queryset.model._meta.ordering
        else:
            order_by = ['pk']

        model_type = connection_type._meta.node._meta.model

        args = args or {}

        before = cls.cursor_to_instance(args.get('before'), model_type)
        after = cls.cursor_to_instance(args.get('after'), model_type)
        first = args.get('first')
        last = args.get('last')

        has_next_page, has_previous_page = False, False
        if before:
            queryset, qs_ex = cls.split_query(queryset, order_by, before)
            has_next_page = True

        if after:
            qs_ex, queryset = cls.split_query(queryset, order_by, after)
            has_previous_page = True

        if isinstance(first, int):
            has_next_page = queryset[first:].exists()
            queryset = queryset[:first]

        if isinstance(last, int):
            logger.warning('performance warning queryset.count called')
            index = max(0, queryset.count() - last)
            has_previous_page = queryset[:index].exists()
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
            iterable = cls.optimize_queryset(connection, iterable, info, args)

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

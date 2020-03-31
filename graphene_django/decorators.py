import graphene
from .types import DjangoObjectType

def query_decorator(wrapper):
    def f(klass):
        get_resolver_for_type = (
            graphene.utils.get_unbound_function.get_unbound_function(
                graphene.types.typemap.TypeMap.get_resolver_for_type))
        for name, field in graphene.types.utils.yank_fields_from_attrs(klass.__dict__).items():
            resolver = get_resolver_for_type(None, type('', (klass, graphene.ObjectType), {}),
                                             name, field.default_value)
            setattr(klass, 'resolve_{}'.format(name), wrapper(resolver))
        return klass
    return f


def node_decorator(wrapper):
    def f(klass):
        print(klass, DjangoObjectType)
        assert issubclass(klass, DjangoObjectType)
        setattr(klass, 'get_queryset', wrapper(klass.get_queryset))
        setattr(klass, 'resolve', wrapper(klass.resolve))
        return klass
    return f

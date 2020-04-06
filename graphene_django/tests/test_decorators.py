import pytest

import graphene

from . import models
from ..registry import reset_global_registry
from ..types import DjangoObjectType
from ..fields import DjangoConnectionField, DefaultDjangoField
from .. import decorators



@pytest.mark.django_db
class TestDecorator:
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = models.Pet
        self.PetType = PetType


    def teardown_method(self, method):
        models.Pet.objects.all().delete()
        reset_global_registry()

    def test_query_decorator(self):
        self.called = 0
        def wrapper(f):
            def g(*args, **kwargs):
                self.called += 1
                return f(*args, **kwargs)
            return g

        @decorators.query_decorator(wrapper)
        class Query(graphene.ObjectType):
            pet = graphene.Field(self.PetType)
            pets = DjangoConnectionField(self.PetType)

            def resolve_pet(root, context):
                return self.PetType(name="pet", age=0)

        schema = graphene.Schema(query=Query)

        query = """
        query {
            pet {
              name
              age
            }
        }
        """

        result = schema.execute(query)
        assert not result.errors
        assert result.data == {'pet': {'name': 'pet', 'age': 0}}
        assert self.called == 1

        query = """
        query {
            pets {
                edges {
                    node {
                        name
                        age
                    }
                }
            }
        }
        """

        result = schema.execute(query)
        assert not result.errors
        assert self.called == 2

    def test_node_decorator(self):
        self.called = 0
        def wrapper(f):
            def g(*args, **kwargs):
                self.called += 1
                return f(*args, **kwargs)
            return g

        PetType = decorators.node_decorator(wrapper)(self.PetType)

        class Query(graphene.ObjectType):
            pet = DefaultDjangoField(self.PetType)


        schema = graphene.Schema(query=Query)

        query = """
        query {
            pet {
              name
              age
            }
        }
        """

        result = schema.execute(query)
        assert not result.errors
        # assert result.data == {'pet': {'name': 'pet', 'age': 0}}
        assert self.called == 1

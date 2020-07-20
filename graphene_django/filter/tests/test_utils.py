import pytest
import django_filters
import graphene

from ...registry import reset_global_registry
from ...tests import models
from ...types import DjangoObjectType
from .. import utils
from ..fields import DjangoFilterConnectionField


class MyFilterSet(django_filters.FilterSet):
    class Meta:
        model = models.Pet
        fields = {
            'name': ['exact', 'icontains', 'istartswith', 'in'],
        }

    order_by = utils.MultipleOrderingFilter(
        fields=(
            ('age', 'age'),
            ('pk', 'pk'),
        )
    )


@pytest.mark.django_db
class TestMultipleOrderingFilter:
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = models.Pet
                exclude = ()
                filterset_class = MyFilterSet
        self.PetType = PetType


    def teardown_method(self, method):
        models.Pet.objects.all().delete()
        reset_global_registry()

    def test_single(self):
        pets = []
        for i in range(1, 6):
            pets.append(models.Pet.objects.create(name='name({})'.format(i),
                                                  age=i))        

        class Query(graphene.ObjectType):
            pets = DjangoFilterConnectionField(self.PetType)

        schema = graphene.Schema(query=Query)

        query = """
        query($first: Int, $orderBy: [String]) {
            pets(first: $first, orderBy: $orderBy) {
                 edges {
                     node {
                         name
                         age
                     }
                 }
            }
        }
        """

        result = schema.execute(query, variable_values={
            "first": 1, "orderBy": ["-pk"],
        })
        assert not result.errors
        assert result.data == {'pets': {'edges': [{'node': {'name': 'name(5)', 'age': 5}}]}}

    def test_multiple(self):
        pets = []
        for i in range(1, 6):
            pets.append(models.Pet.objects.create(name='name({})'.format(i),
                                                  age=(i + 1) // 2))

        class Query(graphene.ObjectType):
            pets = DjangoFilterConnectionField(self.PetType)

        schema = graphene.Schema(query=Query)

        query = """
        query($orderBy: [String]) {
            pets(orderBy: $orderBy) {
                 edges {
                     node {
                         name
                         age
                     }
                 }
            }
        }
        """

        result = schema.execute(query, variable_values={
            "orderBy": ["age", "-pk"],
        })
        assert not result.errors
        assert result.data == {'pets': {'edges': [{'node': {'name': 'name(2)', 'age': 1}}, {'node': {'name': 'name(1)', 'age': 1}}, {'node': {'name': 'name(4)', 'age': 2}}, {'node': {'name': 'name(3)', 'age': 2}}, {'node': {'name': 'name(5)', 'age': 3}}]}}

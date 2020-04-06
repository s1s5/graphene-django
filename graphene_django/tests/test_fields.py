import datetime

import pytest

from graphene import List, NonNull, ObjectType, Schema, String

from ..fields import DjangoListField, DjangoConnectionField
from ..registry import reset_global_registry
from ..types import DjangoObjectType
from .models import Pet as PetModel
from .models import Article as ArticleModel
from .models import Reporter as ReporterModel


@pytest.mark.django_db
class TestDjangoListField:
    def teardown_method(self, method):
        reset_global_registry()

    def test_only_django_object_types(self):
        class TestType(ObjectType):
            foo = String()

        with pytest.raises(AssertionError):
            list_field = DjangoListField(TestType)

    def test_only_import_paths(self):
        list_field = DjangoListField("graphene_django.tests.schema.Human")
        from .schema import Human

        assert list_field._type.of_type.of_type is Human

    def test_non_null_type(self):
        class Reporter(DjangoObjectType):
            class Meta:
                model = ReporterModel
                fields = ("first_name",)

        list_field = DjangoListField(NonNull(Reporter))

        assert isinstance(list_field.type, List)
        assert isinstance(list_field.type.of_type, NonNull)
        assert list_field.type.of_type.of_type is Reporter

    def test_get_django_model(self):
        class Reporter(DjangoObjectType):
            class Meta:
                model = ReporterModel
                fields = ("first_name",)

        list_field = DjangoListField(Reporter)
        assert list_field.model is ReporterModel

    def test_list_field_default_queryset(self):
        class Reporter(DjangoObjectType):
            class Meta:
                model = ReporterModel
                fields = ("first_name",)

        class Query(ObjectType):
            reporters = DjangoListField(Reporter)

        schema = Schema(query=Query)

        query = """
            query {
                reporters {
                    firstName
                }
            }
        """

        ReporterModel.objects.create(first_name="Tara", last_name="West")
        ReporterModel.objects.create(first_name="Debra", last_name="Payne")

        result = schema.execute(query)

        assert not result.errors
        assert result.data == {
            "reporters": [{"firstName": "Tara"}, {"firstName": "Debra"}]
        }

    def test_override_resolver(self):
        class Reporter(DjangoObjectType):
            class Meta:
                model = ReporterModel
                fields = ("first_name",)

        class Query(ObjectType):
            reporters = DjangoListField(Reporter)

            def resolve_reporters(_, info):
                return ReporterModel.objects.filter(first_name="Tara")

        schema = Schema(query=Query)

        query = """
            query {
                reporters {
                    firstName
                }
            }
        """

        ReporterModel.objects.create(first_name="Tara", last_name="West")
        ReporterModel.objects.create(first_name="Debra", last_name="Payne")

        result = schema.execute(query)

        assert not result.errors
        assert result.data == {"reporters": [{"firstName": "Tara"}]}

    def test_nested_list_field(self):
        class Article(DjangoObjectType):
            class Meta:
                model = ArticleModel
                fields = ("headline",)
                use_connection = False

        class Reporter(DjangoObjectType):
            class Meta:
                model = ReporterModel
                fields = ("first_name", "articles")

        class Query(ObjectType):
            reporters = DjangoListField(Reporter)

        schema = Schema(query=Query)

        query = """
            query {
                reporters {
                    firstName
                    articles {
                        headline
                    }
                }
            }
        """

        r1 = ReporterModel.objects.create(first_name="Tara", last_name="West")
        ReporterModel.objects.create(first_name="Debra", last_name="Payne")

        ArticleModel.objects.create(
            headline="Amazing news",
            reporter=r1,
            pub_date=datetime.date.today(),
            pub_date_time=datetime.datetime.now(),
            editor=r1,
        )

        result = schema.execute(query)

        assert not result.errors
        assert result.data == {
            "reporters": [
                {"firstName": "Tara", "articles": [{"headline": "Amazing news"}]},
                {"firstName": "Debra", "articles": []},
            ]
        }

    def test_override_resolver_nested_list_field(self):
        class Article(DjangoObjectType):
            class Meta:
                model = ArticleModel
                fields = ("headline",)
                use_connection = False

        class Reporter(DjangoObjectType):
            class Meta:
                model = ReporterModel
                fields = ("first_name", "articles")

            def resolve_reporters(reporter, info):
                return reporter.articles.all()

        class Query(ObjectType):
            reporters = DjangoListField(Reporter)

        schema = Schema(query=Query)

        query = """
            query {
                reporters {
                    firstName
                    articles {
                        headline
                    }
                }
            }
        """

        r1 = ReporterModel.objects.create(first_name="Tara", last_name="West")
        ReporterModel.objects.create(first_name="Debra", last_name="Payne")

        ArticleModel.objects.create(
            headline="Amazing news",
            reporter=r1,
            pub_date=datetime.date.today(),
            pub_date_time=datetime.datetime.now(),
            editor=r1,
        )

        result = schema.execute(query)

        assert not result.errors
        assert result.data == {
            "reporters": [
                {"firstName": "Tara", "articles": [{"headline": "Amazing news"}]},
                {"firstName": "Debra", "articles": []},
            ]
        }

    def test_split_query(self):
        class PetNode(DjangoObjectType):
            class Meta:
                model = PetModel

        class Query(ObjectType):
            pets = DjangoConnectionField(PetNode)

        pets = []
        for i in range(1, 6):
            pets.append(PetModel.objects.create(name='name({})'.format(i),
                                                age=i))

        schema = Schema(query=Query)

        query = """
            query {
                pets(first: 2) {
                    edges {
                        cursor
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
        assert result.data == {'pets': {'edges': [{'cursor': hex(pets[0].pk), 'node': {'name': 'name(1)', 'age': 1}}, {'cursor': hex(pets[1].pk), 'node': {'name': 'name(2)', 'age': 2}}]}}


        query = """
            query {
                pets(first: 2, after: "%s") {
                    edges {
                        cursor
                        node {
                            name
                            age
                        }
                    }
                }
            }
        """ % hex(pets[1].pk)

        result = schema.execute(query)
        assert not result.errors
        assert result.data == {'pets': {'edges': [{'cursor': hex(pets[2].pk), 'node': {'name': 'name(3)', 'age': 3}}, {'cursor': hex(pets[3].pk), 'node': {'name': 'name(4)', 'age': 4}}]}}


        query = """
            query {
                pets(last: 2, before: "%s") {
                    edges {
                        cursor
                        node {
                            name
                            age
                        }
                    }
                }
            }
        """ % hex(pets[4].pk)

        result = schema.execute(query)
        assert not result.errors
        assert result.data == {'pets': {'edges': [{'cursor': hex(pets[2].pk), 'node': {'name': 'name(3)', 'age': 3}}, {'cursor': hex(pets[3].pk), 'node': {'name': 'name(4)', 'age': 4}}]}}

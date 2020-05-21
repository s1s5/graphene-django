import base64
import datetime
import uuid
import os

import pytest
from django.db import models
from django.utils.functional import SimpleLazyObject
from py.test import raises

from django.db.models import Q

from graphql_relay import to_global_id
import graphene
from graphene.relay import Node

from ..utils import DJANGO_FILTER_INSTALLED
from ..compat import MissingType, JSONField
from ..fields import DjangoConnectionField
from ..registry import reset_global_registry
from ..types import DjangoObjectType
from ..settings import graphene_settings
from .models import Article, CNNReporter, Reporter, Film, FilmDetails, Pet
from ..debug.types import DjangoDebug

pytestmark = pytest.mark.django_db

@pytest.fixture(scope='function', autouse=True)
def clear_global_registry():
    yield
    reset_global_registry()


def test_should_query_only_fields():
    with raises(Exception):

        class ReporterType(DjangoObjectType):
            class Meta:
                model = Reporter
                fields = ("articles",)

        schema = graphene.Schema(query=ReporterType)
        query = """
            query ReporterQuery {
              articles
            }
        """
        result = schema.execute(query)
        assert not result.errors


def test_should_query_simplelazy_objects():
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            fields = ("id",)

    class Query(graphene.ObjectType):
        reporter = graphene.Field(ReporterType)

        def resolve_reporter(self, info):
            return SimpleLazyObject(lambda: Reporter(id=1))

    schema = graphene.Schema(query=Query)
    query = """
        query {
          reporter {
            id
          }
        }
    """
    result = schema.execute(query)
    assert not result.errors
    assert result.data == {"reporter": {"id": 'UmVwb3J0ZXJUeXBlOjE='}}


def test_should_query_well():
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()

    class Query(graphene.ObjectType):
        reporter = graphene.Field(ReporterType)

        def resolve_reporter(self, info):
            return Reporter(first_name="ABA", last_name="X")

    query = """
        query ReporterQuery {
          reporter {
            firstName,
            lastName,
            email
          }
        }
    """
    expected = {"reporter": {"firstName": "ABA", "lastName": "X", "email": ""}}
    schema = graphene.Schema(query=Query)
    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


@pytest.mark.skipif(JSONField is MissingType, reason="RangeField should exist")
def test_should_query_postgres_fields():
    from django.contrib.postgres.fields import (
        IntegerRangeField,
        ArrayField,
        JSONField,
        HStoreField,
    )

    class Event(models.Model):
        ages = IntegerRangeField(help_text="The age ranges")
        data = JSONField(help_text="Data")
        store = HStoreField()
        tags = ArrayField(models.CharField(max_length=50))

    class EventType(DjangoObjectType):
        class Meta:
            model = Event
            exclude = ()

    class Query(graphene.ObjectType):
        event = graphene.Field(EventType)

        def resolve_event(self, info):
            return Event(
                ages=(0, 10),
                data={"angry_babies": True},
                store={"h": "store"},
                tags=["child", "angry", "babies"],
            )

    schema = graphene.Schema(query=Query)
    query = """
        query myQuery {
          event {
            ages
            tags
            data
            store
          }
        }
    """
    expected = {
        "event": {
            "ages": [0, 10],
            "tags": ["child", "angry", "babies"],
            "data": '{"angry_babies": true}',
            "store": '{"h": "store"}',
        }
    }
    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_node():
    # reset_global_registry()
    # Node._meta.registry = get_global_registry()
    reporter = Reporter.objects.create(first_name='a', last_name='b', email='a@b.c')
    Article.objects.create(headline="Hi!",
                           pub_date=datetime.datetime.now().date(),
                           pub_date_time=datetime.datetime.now(),
                           reporter=reporter, editor=reporter)

    class ReporterNode(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

        @classmethod
        def get_node(cls, info, id):
            return Reporter(id=2, first_name="Cookie Monster")

        def resolve_articles(self, info, **args):
            return Article.objects.all()  # [Article(headline="Hi!")]

    class ArticleNode(DjangoObjectType):
        class Meta:
            model = Article
            exclude = ()
            interfaces = (Node,)

        @classmethod
        def get_node(cls, info, id):
            return Article(
                id=1, headline="Article node", pub_date=datetime.date(2002, 3, 11)
            )

    class Query(graphene.ObjectType):
        node = Node.Field()
        reporter = graphene.Field(ReporterNode)
        article = graphene.Field(ArticleNode)

        def resolve_reporter(self, info):
            return Reporter(id=1, first_name="ABA", last_name="X")

    query = """
        query ReporterQuery {
          reporter {
            id,
            firstName,
            articles {
              edges {
                node {
                  headline
                }
              }
            }
            lastName,
            email
          }
          myArticle: node(id:"QXJ0aWNsZU5vZGU6MQ==") {
            id
            ... on ReporterNode {
                firstName
            }
            ... on ArticleNode {
                headline
                pubDate
            }
          }
        }
    """
    expected = {
        "reporter": {
            "id": "UmVwb3J0ZXJOb2RlOjE=",
            "firstName": "ABA",
            "lastName": "X",
            "email": "",
            "articles": {"edges": [{"node": {"headline": "Hi!"}}]},
        },
        "myArticle": {
            "id": "QXJ0aWNsZU5vZGU6MQ==",
            "headline": "Article node",
            "pubDate": "2002-03-11",
        },
    }
    schema = graphene.Schema(query=Query)
    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_onetoone_fields():
    film = Film(id=1)
    film_details = FilmDetails(id=1, film=film)

    class FilmNode(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()
            interfaces = (Node,)

    class FilmDetailsNode(DjangoObjectType):
        class Meta:
            model = FilmDetails
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        film = graphene.Field(FilmNode)
        film_details = graphene.Field(FilmDetailsNode)

        def resolve_film(root, info):
            return film

        def resolve_film_details(root, info):
            return film_details

    query = """
        query FilmQuery {
          filmDetails {
            id
            film {
              id
            }
          }
          film {
            id
            details {
              id
            }
          }
        }
    """
    expected = {
        "filmDetails": {
            "id": "RmlsbURldGFpbHNOb2RlOjE=",
            "film": {"id": "RmlsbU5vZGU6MQ=="},
        },
        "film": {
            "id": "RmlsbU5vZGU6MQ==",
            "details": {"id": "RmlsbURldGFpbHNOb2RlOjE="},
        },
    }
    schema = graphene.Schema(query=Query)
    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_connectionfields():
    reporter = Reporter.objects.create(first_name='a', last_name='b', email='a@b.c')
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            interfaces = (Node,)
            fields = ("articles",)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

        def resolve_all_reporters(self, info, **args):
            return Reporter.objects.all()

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterConnectionQuery {
          allReporters {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
        }
    """
    result = schema.execute(query)
    assert not result.errors
    assert result.data == {
        "allReporters": {
            "pageInfo": {"hasNextPage": False},
            "edges": [{"node": {"id": "UmVwb3J0ZXJUeXBlOjE="}}],
        }
    }


def test_should_keep_annotations():
    from django.db.models import Count, Avg

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            interfaces = (Node,)
            fields = ("articles",)

    class ArticleType(DjangoObjectType):
        class Meta:
            model = Article
            exclude = ()
            interfaces = (Node,)
            filter_fields = ("lang",)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)
        all_articles = DjangoConnectionField(ArticleType)

        def resolve_all_reporters(self, info, **args):
            return Reporter.objects.annotate(articles_c=Count("articles")).order_by(
                "articles_c"
            )

        def resolve_all_articles(self, info, **args):
            return Article.objects.annotate(import_avg=Avg("importance")).order_by(
                "import_avg"
            )

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterConnectionQuery {
          allReporters {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
          allArticles {
            pageInfo {
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
        }
    """
    result = schema.execute(query)
    assert not result.errors


@pytest.mark.skipif(
    not DJANGO_FILTER_INSTALLED, reason="django-filter should be installed"
)
def test_should_query_node_filtering():
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class ArticleType(DjangoObjectType):
        class Meta:
            model = Article
            exclude = ()
            interfaces = (Node,)
            filter_fields = ("lang",)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )
    Article.objects.create(
        headline="Article Node 1",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="es",
    )
    Article.objects.create(
        headline="Article Node 2",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="en",
    )

    schema = graphene.Schema(query=Query)
    query = """
        query NodeFilteringQuery {
            allReporters {
                edges {
                    node {
                        id
                        articles(lang: ES) {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        }
    """

    expected = {
        "allReporters": {
            "edges": [
                {
                    "node": {
                        "id": "UmVwb3J0ZXJUeXBlOjE=",
                        "articles": {
                            "edges": [{"node": {"id": "QXJ0aWNsZVR5cGU6MQ=="}}]
                        },
                    }
                }
            ]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


@pytest.mark.skipif(
    not DJANGO_FILTER_INSTALLED, reason="django-filter should be installed"
)
def test_should_query_node_filtering_with_distinct_queryset():
    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()
            interfaces = (Node,)
            filter_fields = ("genre",)

    class Query(graphene.ObjectType):
        films = DjangoConnectionField(FilmType)

        # def resolve_all_reporters_with_berlin_films(self, args, context, info):
        #    return Reporter.objects.filter(Q(films__film__location__contains="Berlin") | Q(a_choice=1))

        def resolve_films(self, info, **args):
            return Film.objects.filter(
                Q(details__location__contains="Berlin") | Q(genre__in=["ot"])
            ).distinct()

    f = Film.objects.create()
    fd = FilmDetails.objects.create(location="Berlin", film=f)

    schema = graphene.Schema(query=Query)
    query = """
        query NodeFilteringQuery {
            films {
                edges {
                    node {
                        genre
                    }
                }
            }
        }
    """

    expected = {"films": {"edges": [{"node": {"genre": "OT"}}]}}

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


@pytest.mark.skipif(
    not DJANGO_FILTER_INSTALLED, reason="django-filter should be installed"
)
def test_should_query_node_multiple_filtering():
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class ArticleType(DjangoObjectType):
        class Meta:
            model = Article
            exclude = ()
            interfaces = (Node,)
            filter_fields = ("lang", "headline")

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )
    Article.objects.create(
        headline="Article Node 1",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="es",
    )
    Article.objects.create(
        headline="Article Node 2",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="es",
    )
    Article.objects.create(
        headline="Article Node 3",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="en",
    )

    schema = graphene.Schema(query=Query)
    query = """
        query NodeFilteringQuery {
            allReporters {
                edges {
                    node {
                        id
                        articles(lang: ES, headline: "Article Node 1") {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        }
    """

    expected = {
        "allReporters": {
            "edges": [
                {
                    "node": {
                        "id": "UmVwb3J0ZXJUeXBlOjE=",
                        "articles": {
                            "edges": [{"node": {"id": "QXJ0aWNsZVR5cGU6MQ=="}}]
                        },
                    }
                }
            ]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_enforce_first_or_last():
    graphene_settings.RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST = True

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    schema = graphene.Schema(query=Query)
    query = """
        query NodeFilteringQuery {
            allReporters {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": None}

    result = schema.execute(query)
    assert len(result.errors) == 1
    assert str(result.errors[0]) == (
        "You must provide a `first` or `last` value to properly "
        "paginate the `allReporters` connection."
    )
    assert result.data == expected


def test_should_error_if_first_is_greater_than_max():
    graphene_settings.RELAY_CONNECTION_MAX_LIMIT = 100

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    assert Query.all_reporters.max_limit == 100

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    schema = graphene.Schema(query=Query)
    query = """
        query NodeFilteringQuery {
            allReporters(first: 101) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": None}

    result = schema.execute(query)
    assert len(result.errors) == 1
    assert str(result.errors[0]) == (
        "Requesting 101 records on the `allReporters` connection "
        "exceeds the `first` limit of 100 records."
    )
    assert result.data == expected

    graphene_settings.RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST = False


def test_should_error_if_last_is_greater_than_max():
    graphene_settings.RELAY_CONNECTION_MAX_LIMIT = 100

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    assert Query.all_reporters.max_limit == 100

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    schema = graphene.Schema(query=Query)
    query = """
        query NodeFilteringQuery {
            allReporters(last: 101) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": None}

    result = schema.execute(query)
    assert len(result.errors) == 1
    assert str(result.errors[0]) == (
        "Requesting 101 records on the `allReporters` connection "
        "exceeds the `last` limit of 100 records."
    )
    assert result.data == expected

    graphene_settings.RELAY_CONNECTION_ENFORCE_FIRST_OR_LAST = False


def test_should_query_promise_connectionfields():
    from promise import Promise
    reporter = Reporter.objects.create(first_name='a', last_name='b', email='a@b.c')

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

        def resolve_all_reporters(self, info, **args):
            return Promise.resolve(Reporter.objects.all())

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterPromiseConnectionQuery {
            allReporters(first: 1) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": {"edges": [{"node": {"id": "UmVwb3J0ZXJUeXBlOjE="}}]}}

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_connectionfields_with_last():

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

        def resolve_all_reporters(self, info, **args):
            return Reporter.objects.all()

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterLastQuery {
            allReporters(last: 1) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": {"edges": [{"node": {"id": "UmVwb3J0ZXJUeXBlOjE="}}]}}

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_connectionfields_with_manager():

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    r = Reporter.objects.create(
        first_name="John", last_name="NotDoe", email="johndoe@example.com", a_choice=1
    )

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType, on="doe_objects")

        def resolve_all_reporters(self, info, **args):
            return Reporter.objects.all()

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterLastQuery {
            allReporters(first: 1) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": {"edges": [{"node": {"id": "UmVwb3J0ZXJUeXBlOjE="}}]}}

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_query_dataloader_fields():
    from promise import Promise
    from promise.dataloader import DataLoader

    def article_batch_load_fn(keys):
        queryset = Article.objects.filter(reporter_id__in=keys)
        return Promise.resolve(
            [
                [article for article in queryset if article.reporter_id == id]
                for id in keys
            ]
        )

    article_loader = DataLoader(article_batch_load_fn)

    class ArticleType(DjangoObjectType):
        class Meta:
            model = Article
            exclude = ()
            interfaces = (Node,)

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)
            use_connection = True

        articles = DjangoConnectionField(ArticleType)

        def resolve_articles(self, info, **args):
            return article_loader.load(self.id)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    r = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    Article.objects.create(
        headline="Article Node 1",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="es",
    )
    Article.objects.create(
        headline="Article Node 2",
        pub_date=datetime.date.today(),
        pub_date_time=datetime.datetime.now(),
        reporter=r,
        editor=r,
        lang="en",
    )

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterPromiseConnectionQuery {
            allReporters(first: 1) {
                edges {
                    node {
                        id
                        articles(first: 2) {
                            edges {
                                node {
                                    headline
                                }
                            }
                        }
                    }
                }
            }
        }
    """

    expected = {
        "allReporters": {
            "edges": [
                {
                    "node": {
                        "id": "UmVwb3J0ZXJUeXBlOjE=",
                        "articles": {
                            "edges": [
                                {"node": {"headline": "Article Node 1"}},
                                {"node": {"headline": "Article Node 2"}},
                            ]
                        },
                    }
                }
            ]
        }
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_handle_inherited_choices():
    class BaseModel(models.Model):
        choice_field = models.IntegerField(choices=((0, "zero"), (1, "one")))

    class ChildModel(BaseModel):
        class Meta:
            proxy = True

    class BaseType(DjangoObjectType):
        class Meta:
            model = BaseModel
            exclude = ()

    class ChildType(DjangoObjectType):
        class Meta:
            model = ChildModel
            exclude = ()

    class Query(graphene.ObjectType):
        base = graphene.Field(BaseType)
        child = graphene.Field(ChildType)

    schema = graphene.Schema(query=Query)
    query = """
        query {
          child {
            choiceField
          }
        }
    """
    result = schema.execute(query)
    assert not result.errors


def test_proxy_model_support():
    """
    This test asserts that we can query for all Reporters and proxied Reporters.
    """
    graphene_settings.RELAY_CONNECTION_MAX_LIMIT = 0

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)
            use_connection = True

    class CNNReporterType(DjangoObjectType):
        class Meta:
            model = CNNReporter
            exclude = ()
            interfaces = (Node,)
            use_connection = True

    reporter = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )

    cnn_reporter = CNNReporter.objects.create(
        first_name="Some",
        last_name="Guy",
        email="someguy@cnn.com",
        a_choice=1,
        reporter_type=2,  # set this guy to be CNN
    )

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)
        cnn_reporters = DjangoConnectionField(CNNReporterType)

    schema = graphene.Schema(query=Query)
    query = """
        query ProxyModelQuery {
            allReporters {
                edges {
                    node {
                        id
                    }
                }
            }
            cnnReporters {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {
        "allReporters": {
            "edges": [
                {"node": {"id": to_global_id("ReporterType", reporter.id)}},
                {"node": {"id": to_global_id("ReporterType", cnn_reporter.id)}},
            ]
        },
        "cnnReporters": {
            "edges": [
                {"node": {"id": to_global_id("CNNReporterType", cnn_reporter.id)}}
            ]
        },
    }

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_resolve_get_queryset_connectionfields():
    reporter_1 = Reporter.objects.create(
        first_name="John", last_name="Doe", email="johndoe@example.com", a_choice=1
    )
    reporter_2 = CNNReporter.objects.create(
        first_name="Some",
        last_name="Guy",
        email="someguy@cnn.com",
        a_choice=1,
        reporter_type=2,  # set this guy to be CNN
    )

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (Node,)

        @classmethod
        def get_queryset(cls, queryset, info):
            return queryset.filter(reporter_type=2)

    class Query(graphene.ObjectType):
        all_reporters = DjangoConnectionField(ReporterType)

    schema = graphene.Schema(query=Query)
    query = """
        query ReporterPromiseConnectionQuery {
            allReporters(first: 1) {
                edges {
                    node {
                        id
                    }
                }
            }
        }
    """

    expected = {"allReporters": {"edges": [{"node": {"id": "UmVwb3J0ZXJUeXBlOjI="}}]}}

    result = schema.execute(query)
    assert not result.errors
    assert result.data == expected


def test_should_preserve_prefetch_related(django_assert_num_queries):
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (graphene.relay.Node,)

    class FilmType(DjangoObjectType):
        reporters = DjangoConnectionField(ReporterType)

        class Meta:
            model = Film
            exclude = ()
            interfaces = (graphene.relay.Node,)

    class Query(graphene.ObjectType):
        films = DjangoConnectionField(FilmType)

        def resolve_films(root, info):
            qs = Film.objects.prefetch_related("reporters")
            return qs

    r1 = Reporter.objects.create(first_name="Dave", last_name="Smith")
    r2 = Reporter.objects.create(first_name="Jane", last_name="Doe")

    f1 = Film.objects.create()
    f1.reporters.set([r1, r2])
    f2 = Film.objects.create()
    f2.reporters.set([r2])

    query = """
        query {
            films {
                edges {
                    node {
                        reporters {
                            edges {
                                node {
                                    firstName
                                }
                            }
                        }
                    }
                }
            }
        }
    """
    schema = graphene.Schema(query=Query)
    with django_assert_num_queries(2) as captured:  # countを呼ばなくなったので3 -> 2に減らす
        result = schema.execute(query)
    assert not result.errors


def test_should_preserve_annotations():
    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()
            interfaces = (graphene.relay.Node,)

    class FilmType(DjangoObjectType):
        reporters = DjangoConnectionField(ReporterType)
        reporters_count = graphene.Int()

        class Meta:
            model = Film
            exclude = ()
            interfaces = (graphene.relay.Node,)

    class Query(graphene.ObjectType):
        films = DjangoConnectionField(FilmType)

        def resolve_films(root, info):
            qs = Film.objects.prefetch_related("reporters")
            return qs.annotate(reporters_count=models.Count("reporters"))

    r1 = Reporter.objects.create(first_name="Dave", last_name="Smith")
    r2 = Reporter.objects.create(first_name="Jane", last_name="Doe")

    f1 = Film.objects.create()
    f1.reporters.set([r1, r2])
    f2 = Film.objects.create()
    f2.reporters.set([r2])

    query = """
        query {
            films {
                edges {
                    node {
                        reportersCount
                    }
                }
            }
        }
    """
    schema = graphene.Schema(query=Query)
    result = schema.execute(query)
    assert not result.errors, str(result)

    expected = {
        "films": {
            "edges": [{"node": {"reportersCount": 2}}, {"node": {"reportersCount": 1}}]
        }
    }
    assert result.data == expected, str(result.data)


def test_should_fields_converted():
    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()
            interfaces = (Node,)
            # filter_fields = ("genre",)
            fields = ("jacket", "data", "extra_data")

    class Query(graphene.ObjectType):
        films = DjangoConnectionField(FilmType)

        def resolve_films(self, info, **args):
            return Film.objects.filter(
                Q(details__location__contains="Berlin") | Q(genre__in=["ot"])
            ).distinct()

    from django.core.files.base import ContentFile

    from PIL import Image
    import io

    txt_filename = '{}.txt'.format(uuid.uuid4().hex)
    png_filename = '{}.png'.format(uuid.uuid4().hex)

    try:
        f = Film.objects.create()

        f.data.save(txt_filename, ContentFile(b'foo'), save=True)

        bio = io.BytesIO()
        img = Image.new('RGB', (16, 8))
        img.save(bio, format='png')
        f.jacket.save(png_filename, ContentFile(bio.getvalue()), save=True)

        f.extra_data = b'foo'
        f.save()

        txt_filename = os.path.join('tmp/film/data', txt_filename)
        png_filename = os.path.join('tmp/film/jacket', png_filename)

        fd = FilmDetails.objects.create(location="Berlin", film=f)

        schema = graphene.Schema(query=Query)
        query = """
            query NodeFilteringQuery {
                films {
                    edges {
                        node {
                            jacket {
                                name
                                size
                                url
                                width
                                height
                            }
                            data {
                                name
                                size
                                url
                                data
                            }
                            extraData
                        }
                    }
                }
            }
        """

        expected = {
            "films": {"edges": [{"node": {
                "jacket": {
                    "name": png_filename,
                    "size": 71,
                    "url": png_filename,
                    "width": 16,
                    "height": 8,
                },
                "data": {
                    "name": txt_filename,
                    "size": 3,
                    "url": txt_filename,
                    "data": "Zm9v",
                },
                "extraData": "Zm9v",
            }}]}
        }

        result = schema.execute(query)
        assert not result.errors
        assert result.data == expected

        f.data.delete()
        f.jacket.delete()

    finally:
        if os.path.exists(txt_filename):
            os.remove(txt_filename)
        if os.path.exists(png_filename):
            os.remove(png_filename)


def test_queryset_optimize_foreign_key():
    from django.conf import settings
    from django.db import connection, reset_queries
    settings.DEBUG = True

    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()

    class PetType(DjangoObjectType):
        class Meta:
            model = Pet
            exclude = ()

    class Query(graphene.ObjectType):
        films = FilmType.Connection()
        pets = PetType.Connection()
        debug = graphene.Field(DjangoDebug, name="_debug")

    pets, films = [Pet.objects.create(age=0), Pet.objects.create(age=1)], [Film.objects.create(), Film.objects.create(), Film.objects.create(), Film.objects.create()]
    for i in range(2):
        for j in range(2):
            films[2 * i + j].pet = pets[i]
            films[2 * i + j].save()

    schema = graphene.Schema(query=Query)

    query = """
        query {
            films {
                edges {
                    node {
                        id
                        pet {
                            id
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """
    reset_queries()
    result = schema.execute(query)

    assert not result.errors
    assert len(connection.queries) == 1

    query = """
        query {
            pets {
                edges {
                    node {
                        id
                        films {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """

    reset_queries()
    result = schema.execute(query)
    # print(result.errors)
    # print(len(connection.queries))

    assert not result.errors
    assert len(connection.queries) == 2


def test_queryset_optimize_one_to_one():
    from django.conf import settings
    from django.db import connection, reset_queries
    settings.DEBUG = True

    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()

    class FilmDetailsType(DjangoObjectType):
        class Meta:
            model = FilmDetails
            exclude = ()

    class Query(graphene.ObjectType):
        films = FilmType.Connection()
        filmdetails_list = FilmDetailsType.Connection()
        debug = graphene.Field(DjangoDebug, name="_debug")

    for i in range(10):
        film = Film.objects.create()
        film_details = FilmDetails.objects.create(film=film)

    schema = graphene.Schema(query=Query)

    query = """
        query {
            films {
                edges {
                    node {
                        id
                        details {
                            id
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """
    reset_queries()
    result = schema.execute(query)

    assert not result.errors
    assert len(connection.queries) == 1

    query = """
        query {
            filmdetailsList {
                edges {
                    node {
                        id
                        film {
                            id
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """

    reset_queries()
    result = schema.execute(query)
    assert not result.errors
    assert len(connection.queries) == 1


def test_queryset_optimize_many_to_many():
    from django.conf import settings
    from django.db import connection, reset_queries
    settings.DEBUG = True

    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()

    class Query(graphene.ObjectType):
        films = FilmType.Connection()
        reporters = ReporterType.Connection()
        debug = graphene.Field(DjangoDebug, name="_debug")

    films, reporters = [], []
    for i in range(10):
        films.append(Film.objects.create())
        reporters.append(Reporter.objects.create())

    for film in films:
        for reporter in reporters:
            film.reporters.add(reporter)

    schema = graphene.Schema(query=Query)

    query = """
        query {
            films {
                edges {
                    node {
                        id
                        reporters {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """
    reset_queries()
    result = schema.execute(query)

    # print(len(connection.queries))
    # print(result.data)
    # print(result.errors)
    assert not result.errors
    assert len(connection.queries) == 2

    query = """
        query {
            reporters {
                edges {
                    node {
                        id
                        films {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """
    reset_queries()
    result = schema.execute(query)

    # print(len(connection.queries))
    # print(result.data)
    # print(result.errors)
    assert not result.errors
    assert len(connection.queries) == 2


def test_queryset_optimize_recursive():
    from django.conf import settings
    from django.db import connection, reset_queries
    settings.DEBUG = True

    class FilmType(DjangoObjectType):
        class Meta:
            model = Film
            exclude = ()

    class FilmDetailsType(DjangoObjectType):
        class Meta:
            model = FilmDetails
            exclude = ()

    class ReporterType(DjangoObjectType):
        class Meta:
            model = Reporter
            exclude = ()

    class Query(graphene.ObjectType):
        films = FilmType.Connection()
        filmdetails_list = FilmDetailsType.Connection()
        reporters = ReporterType.Connection()
        debug = graphene.Field(DjangoDebug, name="_debug")

    films, reporters = [], []
    for i in range(10):
        films.append(Film.objects.create())
        FilmDetails.objects.create(film=films[-1])
        reporters.append(Reporter.objects.create())

    for film in films:
        for reporter in reporters:
            film.reporters.add(reporter)

    schema = graphene.Schema(query=Query)

    query = """
        query {
            films {
                edges {
                    node {
                        id
                        reporters {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                        details {
                            id
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """
    reset_queries()
    result = schema.execute(query)

    # print(len(connection.queries))
    # print(result.data)
    # print(result.errors)
    assert not result.errors
    assert len(connection.queries) == 2

    # reset_queries()
    # [x for x in Reporter.objects.all().prefetch_related('films').prefetch_related('films__details')]
    # print(len(connection.queries))

    query = """
        query {
            reporters {
                edges {
                    node {
                        id
                        films {
                            edges {
                                node {
                                    id
                                    details {
                                        id
                                    }
                                }
                            }
                        }
                    }
                }
            }
            _debug {
                sql {
                    rawSql
                }
            }
        }
    """
    reset_queries()
    result = schema.execute(query)

    # print(len(connection.queries))
    # for query in connection.queries:
    #     print(query)
    # print(result.data)
    # print(result.errors)
    assert not result.errors
    assert len(connection.queries) == 3


def test_queryset_connection_args():
    class PetType(DjangoObjectType):
        counter = 0
        class Meta:
            model = Pet
            exclude = ()

        @classmethod
        def get_queryset(cls, queryset, info):
            cls.counter += 1
            return queryset

    class Query(graphene.ObjectType):
        pets = PetType.Connection(age=graphene.Int(required=True))

        def resolve_pets(root, info, age, *args, **kwargs):
            return Pet.objects.all().filter(age=age)


    [Pet.objects.create(age=0) for x in range(10)]
    [Pet.objects.create(age=1) for x in range(10)]
    [Pet.objects.create(age=2) for x in range(10)]

    schema = graphene.Schema(query=Query)
    # print(schema)

    query = """
        query {
            pets {
                edges {
                    node {
                        id
                        age
                    }
                }
            }
        }
    """
    result = schema.execute(query)
    assert result.errors[0].message == 'Field "pets" argument "age" of type "Int!" is required but not provided.'
    assert result.data is None
    assert PetType.counter == 0

    query = """
        query {
            pets(age: 1, first: 3) {
                edges {
                    node {
                        id
                        age
                    }
                }
            }
        }
    """
    result = schema.execute(query)
    # print(result.errors)
    # print(result.data)
    assert result.errors is None
    assert len(result.data['pets']['edges']) == 3
    assert [x['node']['age'] for x in result.data['pets']['edges']] == [1, 1, 1]
    assert PetType.counter == 1

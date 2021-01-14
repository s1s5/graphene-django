import datetime

import pytest

from graphql_relay import to_global_id
import graphene
from graphene import List, NonNull, ObjectType, Schema, String

from ..fields import DjangoListField, DjangoConnectionField
from ..registry import reset_global_registry
from ..types import DjangoObjectType
from .models import Pet as PetModel
from .models import FilmDetails as FilmDetailsModel
from .models import Film as FilmModel
from .models import Article as ArticleModel
from .models import Reporter as ReporterModel


def test_related_model():
    assert DjangoConnectionField._get_related_model(PetModel.reporter) == (True, ReporterModel)
    assert DjangoConnectionField._get_related_model(PetModel.films) == (False, FilmModel)
    assert DjangoConnectionField._get_related_model(FilmDetailsModel.film) == (True, FilmModel)
    assert DjangoConnectionField._get_related_model(FilmModel.details) == (True, FilmDetailsModel)
    assert DjangoConnectionField._get_related_model(FilmModel.reporters) == (False, ReporterModel)
    assert DjangoConnectionField._get_related_model(ReporterModel.films) == (False, FilmModel)


@pytest.mark.django_db
class TestDefaultDjangoField:
    def setup_method(self, method):
        class FilmDetailsType(DjangoObjectType):
            called = {}

            class Meta:
                model = FilmDetailsModel
                exclude = ()

            @classmethod
            def get_queryset(cls, queryset, info):
                cls.called['get_queryset'] = cls.called.get('get_queryset', 0) + 1
                return queryset

            @classmethod
            def resolve(cls, resolved, parent, info):
                cls.called['resolve'] = cls.called.get('resolve', 0) + 1
                return resolved

        class FilmType(DjangoObjectType):
            called = {}

            class Meta:
                model = FilmModel
                exclude = ()

            @classmethod
            def get_queryset(cls, queryset, info):
                cls.called['get_queryset'] = cls.called.get('get_queryset', 0) + 1
                return queryset

            @classmethod
            def resolve(cls, resolved, parent, info):
                cls.called['resolve'] = cls.called.get('resolve', 0) + 1
                return resolved

        class ReporterType(DjangoObjectType):
            called = {}

            class Meta:
                model = ReporterModel
                exclude = ()

            @classmethod
            def get_queryset(cls, queryset, info):
                cls.called['get_queryset'] = cls.called.get('get_queryset', 0) + 1
                return queryset

            @classmethod
            def resolve(cls, resolved, parent, info):
                cls.called['resolve'] = cls.called.get('resolve', 0) + 1
                return resolved

        class Query(ObjectType):
            film = FilmType.Node()
            films = FilmType.Connection()
            film_with_genre = FilmType.Field(id=graphene.ID(), g=graphene.String())

            def resolve_film_with_genre(root, info, id=None, g=None):
                if id:
                    return graphene.relay.Node.get_node_from_global_id(info, id)
                try:
                    return FilmModel.objects.get(genre=g)
                except FilmModel.DoesNotExist:
                    return None

        self.FilmDetailsType = FilmDetailsType
        self.FilmType = FilmType
        self.ReporterType = ReporterType

        self.schema = Schema(query=Query)
        self.film = FilmModel.objects.create(genre='do')
        self.reporter = ReporterModel.objects.create()
        self.film.reporters.add(self.reporter)
        self.film.save()
        self.film_details = FilmDetailsModel.objects.create(location='a', film=self.film)

    
    def teardown_method(self, method):
        reset_global_registry()

    def test_resolve_called_single(self):
        gid = to_global_id('FilmType', self.film.pk)
        query = """
            query {
                film(id: "%s") {
                    id
                }
            }
        """ % (gid, )
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'film': {'id': gid}}
        assert self.FilmType.called['get_queryset'] == 1
        assert self.FilmType.called['resolve'] == 1

    def test_resolve_called_single_no_id(self):
        gid = to_global_id('FilmType', self.film.pk)
        query = """
            query {
                filmWithGenre(g: "do") {
                    id
                }
            }
        """
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'filmWithGenre': {'id': gid}}
        assert self.FilmType.called.get('get_queryset', 0) == 0
        assert self.FilmType.called['resolve'] == 1

    def test_resolve_called_single_no_id_2(self):
        gid = to_global_id('FilmType', self.film.pk)
        query = """
            query {
                filmWithGenre(id: "%s") {
                    id
                }
            }
        """ % (gid, )
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'filmWithGenre': {'id': gid}}
        assert self.FilmType.called['get_queryset'] == 1
        assert self.FilmType.called['resolve'] == 1

    def test_resolve_called_single_no_id_error(self):
        gid = to_global_id('FilmType', self.film.pk)
        query = """
            query {
                filmWithGenre(g: "ot") {
                    id
                }
            }
        """
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'filmWithGenre': None}
        assert self.FilmType.called.get('get_queryset', 0) == 0
        assert self.FilmType.called['resolve'] == 1

    def test_resolve_called_multi(self):
        gid = to_global_id('FilmType', self.film.pk)
        query = """
            query {
                films {
                    edges {
                        node {
                            id
                        }
                    }
                }
            }
        """
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'films': {'edges': [{'node': {'id': gid}}]}}
        assert self.FilmType.called['get_queryset'] == 1
        assert self.FilmType.called.get('resolve', 0) == 0

    def test_resolve_onetoone(self):
        film_gid = to_global_id('FilmType', self.film.pk)
        film_details_gid = to_global_id('FilmDetailsType', self.film_details.pk)
        query = """
            query {
                film(id: "%s") {
                    id
                    details {
                        id
                    }
                }
            }
        """ % (film_gid, )
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'film': {'id': film_gid, 'details': {'id': film_details_gid}}}
        assert self.FilmType.called.get('get_queryset', 0) == 1
        assert self.FilmType.called.get('resolve', 0) == 1
        assert self.FilmDetailsType.called.get('get_queryset', 0) == 0
        assert self.FilmDetailsType.called.get('resolve', 0) == 1
        
    def test_resolve_manytomany(self):
        film_gid = to_global_id('FilmType', self.film.pk)
        reporter_gid = to_global_id('ReporterType', self.reporter.pk)
        query = """
            query {
                film(id: "%s") {
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
        """ % (film_gid, )
        result = self.schema.execute(query)
        assert not result.errors
        assert result.data == {'film': {'id': film_gid, 'reporters': {'edges': [{'node': {'id': reporter_gid}}]}}}
        assert self.FilmType.called.get('get_queryset', 0) == 1
        assert self.FilmType.called.get('resolve', 0) == 1
        assert self.ReporterType.called.get('get_queryset', 0) == 1
        assert self.ReporterType.called.get('resolve', 0) == 0

    def test_resolve_onetoone_nest(self):
        film_gid = to_global_id('FilmType', self.film.pk)
        film_details_gid = to_global_id('FilmDetailsType', self.film_details.pk)
        reporter_gid = to_global_id('ReporterType', self.reporter.pk)
        query = """
            query {
                film(id: "%s") {
                    id
                    details {
                        id
                        film {
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
            }
        """ % (film_gid, )
        result = self.schema.execute(query)
        # print(result.data)
        assert not result.errors
        assert result.data == {'film': {'id': film_gid, 'details': {'id': film_details_gid, 'film': {'id': film_gid, 'reporters': {'edges': [{'node': {'id': reporter_gid}}]}}}}}
        assert self.FilmType.called.get('get_queryset', 0) == 1
        assert self.FilmType.called.get('resolve', 0) == 2
        assert self.FilmDetailsType.called.get('get_queryset', 0) == 0
        assert self.FilmDetailsType.called.get('resolve', 0) == 1
        assert self.ReporterType.called.get('get_queryset', 0) == 1
        assert self.ReporterType.called.get('resolve', 0) == 0


    def test_resolve_onetoone_nest_deep(self):
        film_gid = to_global_id('FilmType', self.film.pk)
        film_details_gid = to_global_id('FilmDetailsType', self.film_details.pk)
        reporter_gid = to_global_id('ReporterType', self.reporter.pk)
        query = """
            query {
                film(id: "%s") {  # Film::resolve, Film::get_queryset一回目
                    id
                    details {   # FilmDetails::resolve一回目
                        id
                        film {    # Film::resolve二回目
                            id
                            reporters {   # Reporter::get_queryset一回目
                                edges {
                                    node {
                                        id
                                        films {    # Film::get_queryset二回目
                                            edges {
                                                node {
                                                    id
                                                    details {    # FilmDetails::resolve二回目
                                                        id
                                                        film {    # Film::resolve三回目
                                                            id
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        """ % (film_gid, )
        result = self.schema.execute(query)
        # print(result.data)
        assert not result.errors
        # assert result.data == {'film': {'id': film_gid, 'details': {'id': film_details_gid, 'film': {'id': film_gid, 'reporters': {'edges': [{'node': {'id': reporter_gid}}]}}}}}
        assert self.FilmType.called.get('get_queryset', 0) == 2
        assert self.FilmType.called.get('resolve', 0) == 3
        assert self.FilmDetailsType.called.get('get_queryset', 0) == 0
        assert self.FilmDetailsType.called.get('resolve', 0) == 2
        assert self.ReporterType.called.get('get_queryset', 0) == 1
        assert self.ReporterType.called.get('resolve', 0) == 0



@pytest.mark.django_db
class TestDjangoListField:
    def teardown_method(self, method):
        reset_global_registry()

    def test_only_django_object_types(self):
        class TestType(ObjectType):
            foo = String()

        with pytest.raises(AssertionError):
            list_field = DjangoListField(TestType)

    @pytest.mark.skipif(True, reason='maybe never use')
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

    # def test_split_query(self):
    #     class PetNode(DjangoObjectType):
    #         class Meta:
    #             model = PetModel
    #             exclude = ()

    #     class Query(ObjectType):
    #         pets = DjangoConnectionField(PetNode)

    #     pets = []
    #     for i in range(1, 6):
    #         pets.append(PetModel.objects.create(name='name({})'.format(i),
    #                                             age=i))

    #     schema = Schema(query=Query)

    #     query = """
    #         query {
    #             pets(first: 2) {
    #                 edges {
    #                     cursor
    #                     node {
    #                         name
    #                         age
    #                     }
    #                 }
    #             }
    #         }
    #     """

    #     result = schema.execute(query)
    #     assert not result.errors
    #     assert result.data == {'pets': {'edges': [{'cursor': hex(pets[0].pk), 'node': {'name': 'name(1)', 'age': 1}}, {'cursor': hex(pets[1].pk), 'node': {'name': 'name(2)', 'age': 2}}]}}


    #     query = """
    #         query {
    #             pets(first: 2, after: "%s") {
    #                 edges {
    #                     cursor
    #                     node {
    #                         name
    #                         age
    #                     }
    #                 }
    #             }
    #         }
    #     """ % hex(pets[1].pk)

    #     result = schema.execute(query)
    #     assert not result.errors
    #     assert result.data == {'pets': {'edges': [{'cursor': hex(pets[2].pk), 'node': {'name': 'name(3)', 'age': 3}}, {'cursor': hex(pets[3].pk), 'node': {'name': 'name(4)', 'age': 4}}]}}


    #     query = """
    #         query {
    #             pets(last: 2, before: "%s") {
    #                 edges {
    #                     cursor
    #                     node {
    #                         name
    #                         age
    #                     }
    #                 }
    #             }
    #         }
    #     """ % hex(pets[4].pk)

    #     result = schema.execute(query)
    #     assert not result.errors
    #     assert result.data == {'pets': {'edges': [{'cursor': hex(pets[2].pk), 'node': {'name': 'name(3)', 'age': 3}}, {'cursor': hex(pets[3].pk), 'node': {'name': 'name(4)', 'age': 4}}]}}


@pytest.mark.django_db
class TestDjangoConnectionField:
    def setup_method(self, method):
        class ReporterType(DjangoObjectType):
            class Meta:
                model = ReporterModel
                exclude = ()

        class Query(ObjectType):
            reporters = ReporterType.Connection()

        self.schema = Schema(query=Query)
        self.reporters = []
        n = ['d', 'a', 'b', 'c', 'f', 'a', 'e', 'f', 'g', 'h']
        for i in range(10):
            self.reporters.append(ReporterModel.objects.create(first_name=n[i]))

    
    def teardown_method(self, method):
        reset_global_registry()

    def test_instance(self):
        assert isinstance(self.schema._query.reporters, DjangoConnectionField)

    # def test_pk(self):
    #     before, after = DjangoConnectionField.get_before_and_after_cursor(['pk'], self.reporters[2])
    #     assert before == DjangoConnectionField.instance_to_cursor(self.reporters[1])
    #     assert after == DjangoConnectionField.instance_to_cursor(self.reporters[3])
        
    # def test_pk_reverse(self):
    #     before, after = DjangoConnectionField.get_before_and_after_cursor(['-pk'], self.reporters[2])
    #     assert before == DjangoConnectionField.instance_to_cursor(self.reporters[3])
    #     assert after == DjangoConnectionField.instance_to_cursor(self.reporters[1])
        
    # def test_multiple_0(self):
    #     ll = list(sorted(self.reporters, key=lambda x: (x.first_name, x.pk)))
    #     for i in range(len(self.reporters)):
    #         before, after = DjangoConnectionField.get_before_and_after_cursor(['first_name', 'pk'], self.reporters[i])
    #         index = [x.pk for x in ll].index(self.reporters[i].pk)
    #         if index == 0:
    #             assert before is None
    #         else:
    #             assert before == DjangoConnectionField.instance_to_cursor(ll[index - 1])
    #         if index == len(self.reporters) - 1:
    #             assert after is None
    #         else:
    #             assert after == DjangoConnectionField.instance_to_cursor(ll[index + 1])

    # def test_multiple_1(self):
    #     ll = list(sorted(self.reporters, key=lambda x: (x.first_name, - x.pk)))
    #     for i in range(len(self.reporters)):
    #         before, after = DjangoConnectionField.get_before_and_after_cursor(['first_name', '-pk'], self.reporters[i])
    #         index = [x.pk for x in ll].index(self.reporters[i].pk)
    #         if index == 0:
    #             assert before is None
    #         else:
    #             assert before == DjangoConnectionField.instance_to_cursor(ll[index - 1])
    #         if index == len(self.reporters) - 1:
    #             assert after is None
    #         else:
    #             assert after == DjangoConnectionField.instance_to_cursor(ll[index + 1])

    # def test_multiple_2(self):
    #     ll = list(reversed(sorted(self.reporters, key=lambda x: (x.first_name, x.pk))))
    #     for i in range(len(self.reporters)):
    #         before, after = DjangoConnectionField.get_before_and_after_cursor(['-first_name', '-pk'], self.reporters[i])
    #         index = [x.pk for x in ll].index(self.reporters[i].pk)
    #         if index == 0:
    #             assert before is None
    #         else:
    #             assert before == DjangoConnectionField.instance_to_cursor(ll[index - 1])
    #         if index == len(self.reporters) - 1:
    #             assert after is None
    #         else:
    #             assert after == DjangoConnectionField.instance_to_cursor(ll[index + 1])

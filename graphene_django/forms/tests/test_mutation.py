import pytest
import io
import os
from PIL import Image
import uuid

from django import forms
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.base import ContentFile
from django.utils.datastructures import MultiValueDict

from py.test import raises

from graphene import ObjectType, Schema, String, Field
from graphene_django import DjangoObjectType
from graphene_django.tests.models import Film, FilmDetails, Pet, Reporter, Article

from graphql_relay import to_global_id


from ...settings import graphene_settings
from ..mutation import (
    GrapheneModelForm,
    DjangoFormMutation,
    DjangoCreateModelMutation,
    DjangoGetOrCreateModelMutation,
    DjangoUpdateModelMutation,
    DjangoDeleteModelMutation,
)

from ...registry import reset_global_registry


class MyForm(forms.Form):
    text = forms.CharField()

    def clean_text(self):
        text = self.cleaned_data["text"]
        if text == "INVALID_INPUT":
            raise ValidationError("Invalid input")
        return text

    def save(self):
        pass


class TestForm(forms.Form):
    a = forms.CharField()
    b = forms.CharField()

    def clean_a(self):
        text = self.cleaned_data["a"]
        if text == "INVALID_INPUT":
            raise ValidationError("Invalid input")
        return text

    def save(self):
        pass


class PetForm(forms.ModelForm):
    class Meta:
        model = Pet
        fields = "__all__"


# @pytest.fixture(scope='function', autouse=True)
# def types():
#     class PetType(DjangoObjectType):
#         class Meta:
#             model = Pet
#             fields = "__all__"


#     class FilmType(DjangoObjectType):
#         class Meta:
#             model = Film
#             fields = "__all__"


#     class FilmDetailsType(DjangoObjectType):
#         class Meta:
#             model = FilmDetails
#             fields = "__all__"

#     yield PetType, FilmType, FilmDetails

#     reset_global_registry()


def test_needs_form_class():
    with raises(Exception) as exc:

        class MyMutation(DjangoFormMutation):
            pass

    assert exc.value.args[0] == "form_class is required for DjangoFormMutation"


def test_has_output_fields():
    class MyMutation(DjangoFormMutation):
        class Meta:
            form_class = MyForm

    assert "errors" in MyMutation._meta.fields


def test_has_input_fields():
    class MyMutation(DjangoFormMutation):
        class Meta:
            form_class = MyForm

    assert "text" in MyMutation.Input._meta.fields


@pytest.fixture()
def pet_type():
    class PetType(DjangoObjectType):
        class Meta:
            model = Pet
            fields = "__all__"
    yield PetType
    reset_global_registry()


def test_mutation_error_camelcased(pet_type):
    class ExtraPetForm(PetForm):
        test_field = forms.CharField(required=True)

    class PetMutation(DjangoCreateModelMutation):
        class Meta:
            form_class = ExtraPetForm

    result = PetMutation.mutate_and_get_payload(None, None)
    assert {f.field for f in result.errors} == {"name", "age", "testField"}
    graphene_settings.CAMELCASE_ERRORS = False
    result = PetMutation.mutate_and_get_payload(None, None)
    assert {f.field for f in result.errors} == {"name", "age", "test_field"}
    graphene_settings.CAMELCASE_ERRORS = True



class MockQuery(ObjectType):
    a = String()


class FormMutationTests(TestCase):
    def test_form_invalid_form(self):
        class MyMutation(DjangoFormMutation):
            class Meta:
                form_class = MyForm

        class Mutation(ObjectType):
            my_mutation = MyMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """ mutation MyMutation {
                myMutation(input: { text: "INVALID_INPUT" }) {
                    errors {
                        field
                        messages
                    }
                    text
                }
            }
            """
        )

        self.assertIs(result.errors, None)
        self.assertEqual(
            result.data["myMutation"]["errors"],
            [{"field": "text", "messages": ["Invalid input"]}],
        )

    def test_form_valid_input(self):
        class MyMutation(DjangoFormMutation):
            class Meta:
                form_class = MyForm

        class Mutation(ObjectType):
            my_mutation = MyMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """ mutation MyMutation {
                myMutation(input: { text: "VALID_INPUT" }) {
                    errors {
                        field
                        messages
                    }
                    text
                }
            }
            """
        )

        self.assertIs(result.errors, None)
        self.assertEqual(result.data["myMutation"]["errors"], [])
        self.assertEqual(result.data["myMutation"]["text"], "VALID_INPUT")


    def test_form_only_valid(self):
        class TestMutation(DjangoFormMutation):
            class Meta:
                form_class = TestForm
                only_fields = ('a')

            @classmethod
            def get_form_kwargs(cls, root, info, **input):
                return super().get_form_kwargs(root, info, b="hello-b", **input)

        class Mutation(ObjectType):
            m = TestMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """
             mutation {
                 m(input: { a: "VALID_INPUT" }) {
                    errors {
                        field
                        messages
                    }
                    a
                }
            }
            """
        )
        self.assertIs(result.errors, None)
        self.assertEqual(result.data['m']['a'], 'VALID_INPUT')


    def test_form_only_error(self):
        class TestMutation(DjangoFormMutation):
            class Meta:
                form_class = TestForm
                only_fields = ('a')

            @classmethod
            def get_form_kwargs(cls, root, info, **input):
                return super().get_form_kwargs(root, info, b="hello-b", **input)

        class Mutation(ObjectType):
            m = TestMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """
             mutation {
                 m(input: { a: "INVALID_INPUT" }) {
                    errors {
                        field
                        messages
                    }
                    a
                }
            }
            """
        )
        self.assertIs(result.errors, None)
        self.assertEqual(result.data['m']['errors'], [{'field': 'a', 'messages': ['Invalid input']}])
        self.assertEqual(result.data['m']['a'], 'INVALID_INPUT')


    def test_form_exclude_valid(self):
        class TestMutation(DjangoFormMutation):
            class Meta:
                form_class = TestForm
                exclude_fields = ('b')

            @classmethod
            def get_form_kwargs(cls, root, info, **input):
                return super().get_form_kwargs(root, info, b="hello-b", **input)

        class Mutation(ObjectType):
            m = TestMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """
             mutation {
                 m(input: { a: "VALID_INPUT" }) {
                    errors {
                        field
                        messages
                    }
                    a
                }
            }
            """
        )
        self.assertIs(result.errors, None)
        self.assertEqual(result.data['m']['a'], 'VALID_INPUT')


    def test_form_exclude_error(self):
        class TestMutation(DjangoFormMutation):
            class Meta:
                form_class = TestForm
                exclude_fields = ('b')

            @classmethod
            def get_form_kwargs(cls, root, info, **input):
                return super().get_form_kwargs(root, info, b="hello-b", **input)

        class Mutation(ObjectType):
            m = TestMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """
             mutation {
                 m(input: { a: "INVALID_INPUT" }) {
                    errors {
                        field
                        messages
                    }
                    a
                }
            }
            """
        )
        self.assertIs(result.errors, None)
        self.assertEqual(result.data['m']['errors'], [{'field': 'a', 'messages': ['Invalid input']}])
        self.assertEqual(result.data['m']['a'], 'INVALID_INPUT')



@pytest.mark.django_db
class ModelFormMutationTests(TestCase):
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = Pet
                fields = "__all__"

        class FilmType(DjangoObjectType):
            class Meta:
                model = Film
                fields = "__all__"

        class FilmDetailsType(DjangoObjectType):
            class Meta:
                model = FilmDetails
                fields = "__all__"

        class ReporterType(DjangoObjectType):
            class Meta:
                model = Reporter
                fields = "__all__"

        class ArticleType(DjangoObjectType):
            class Meta:
                model = Article
                fields = "__all__"

        self.PetType = PetType

    def teardown_method(self, method):
        reset_global_registry()

    def test_default_meta_fields(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = PetForm

        self.assertEqual(PetMutation._meta.model, Pet)
        self.assertEqual(PetMutation._meta.return_field_name, "pet")
        self.assertIn("pet", PetMutation._meta.fields)

    def test_default_create_input_meta_fields(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = PetForm

        self.assertEqual(PetMutation._meta.model, Pet)
        self.assertEqual(PetMutation._meta.return_field_name, "pet")
        self.assertIn("name", PetMutation.Input._meta.fields)
        self.assertIn("client_mutation_id", PetMutation.Input._meta.fields)

    def test_default_update_input_meta_fields(self):
        class PetMutation(DjangoUpdateModelMutation):
            class Meta:
                form_class = PetForm

        self.assertEqual(PetMutation._meta.model, Pet)
        self.assertEqual(PetMutation._meta.return_field_name, "pet")
        self.assertIn("name", PetMutation.Input._meta.fields)
        self.assertIn("client_mutation_id", PetMutation.Input._meta.fields)
        self.assertIn("id", PetMutation.Input._meta.fields)

    def test_default_update_input_meta_fields_auto_gen(self):
        class PetMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', )

        self.assertEqual(PetMutation._meta.model, Pet)
        self.assertEqual(PetMutation._meta.return_field_name, "pet")
        self.assertIn("name", PetMutation.Input._meta.fields)
        self.assertIn("client_mutation_id", PetMutation.Input._meta.fields)
        self.assertIn("id", PetMutation.Input._meta.fields)
        self.assertIn("name", PetMutation.Input._meta.fields)
        self.assertNotIn("age", PetMutation.Input._meta.fields)


    def test_default_update_input_meta_fields_auto_gen_execute_error(self):
        pet = Pet.objects.create(name='name', age=0)

        class PetMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Pet
                fields = ('age', )

        class Mutation(ObjectType):
            pet_update = PetMutation.Field()

        schema = Schema(mutation=Mutation)
        result = schema.execute(
            """ mutation PetMutation($pk: ID!, $name: String!) {
                petUpdate(input: { id: $pk, name: $name }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        id
                        name
                        age
                    }
                }
            }
            """,
            variable_values={"pk": to_global_id('PetType', 1), 'name': 'new-name'},
        )

        assert len(result.errors) == 1


    def test_exclude_fields_input_meta_fields(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = PetForm
                exclude_fields = ["id"]

        self.assertEqual(PetMutation._meta.model, Pet)
        self.assertEqual(PetMutation._meta.return_field_name, "pet")
        self.assertIn("name", PetMutation.Input._meta.fields)
        self.assertIn("age", PetMutation.Input._meta.fields)
        self.assertIn("client_mutation_id", PetMutation.Input._meta.fields)
        self.assertNotIn("id", PetMutation.Input._meta.fields)

    def test_return_field_name_is_camelcased(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = PetForm
                model = FilmDetails

        self.assertEqual(PetMutation._meta.model, FilmDetails)
        self.assertEqual(PetMutation._meta.return_field_name, "filmDetails")

    def test_custom_return_field_name(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = PetForm
                model = Film
                return_field_name = "animal"

        self.assertEqual(PetMutation._meta.model, Film)
        self.assertEqual(PetMutation._meta.return_field_name, "animal")
        self.assertIn("animal", PetMutation._meta.fields)

    def test_model_form_mutation_mutate_existing(self):
        class PetMutation(DjangoUpdateModelMutation):
            pet = Field(self.PetType)

            class Meta:
                form_class = PetForm

        class Mutation(ObjectType):
            pet_mutation = PetMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        pet = Pet.objects.create(name="Axel", age=10)

        result = schema.execute(
            """ mutation PetMutation($pk: ID!) {
                petMutation(input: { id: $pk, name: "Mia", age: 10 }) {
                    pet {
                        name
                        age
                    }
                }
            }
            """,
            variable_values={"pk": to_global_id('PetType', pet.pk)},
        )

        self.assertIs(result.errors, None)
        self.assertEqual(result.data["petMutation"]["pet"], {"name": "Mia", "age": 10})

        self.assertEqual(Pet.objects.count(), 1)
        pet.refresh_from_db()
        self.assertEqual(pet.name, "Mia")

    def test_model_form_mutation_creates_new(self):
        class PetMutation(DjangoCreateModelMutation):
            pet = Field(self.PetType)

            class Meta:
                form_class = PetForm

        class Mutation(ObjectType):
            pet_mutation = PetMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """ mutation PetMutation {
                petMutation(input: { name: "Mia", age: 10 }) {
                    pet {
                        name
                        age
                    }
                }
            }
            """
        )
        self.assertIs(result.errors, None)
        self.assertEqual(result.data["petMutation"]["pet"], {"name": "Mia", "age": 10})

        self.assertEqual(Pet.objects.count(), 1)
        pet = Pet.objects.get()
        self.assertEqual(pet.name, "Mia")
        self.assertEqual(pet.age, 10)

    def test_model_form_mutation_creates_new_auto_generate_form(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', 'age')

        class Mutation(ObjectType):
            pet_mutation = PetMutation.Field()

        schema = Schema(query=MockQuery, mutation=Mutation)

        result = schema.execute(
            """ mutation PetMutation {
                petMutation(input: { name: "Mia", age: 10 }) {
                    pet {
                        name
                        age
                    }
                }
            }
            """
        )
        self.assertIs(result.errors, None)
        self.assertEqual(result.data["petMutation"]["pet"], {"name": "Mia", "age": 10})

        self.assertEqual(Pet.objects.count(), 1)
        pet = Pet.objects.get()
        self.assertEqual(pet.name, "Mia")
        self.assertEqual(pet.age, 10)

    def test_model_form_mutation_mutate_invalid_form(self):
        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = PetForm

        result = PetMutation.mutate_and_get_payload(None, None)

        # A pet was not created
        self.assertEqual(Pet.objects.count(), 0)

        fields_w_error = [e.field for e in result.errors]
        self.assertEqual(len(result.errors), 2)
        self.assertIn("name", fields_w_error)
        self.assertEqual(result.errors[0].messages, ["This field is required."])
        self.assertIn("age", fields_w_error)
        self.assertEqual(result.errors[1].messages, ["This field is required."])


@pytest.mark.django_db
class CreateModelMutationTests(TestCase):
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = Pet
                fields = "__all__"

        class FilmType(DjangoObjectType):
            class Meta:
                model = Film
                fields = "__all__"

        class FilmDetailsType(DjangoObjectType):
            class Meta:
                model = FilmDetails
                fields = "__all__"

        class ReporterType(DjangoObjectType):
            class Meta:
                model = Reporter
                fields = "__all__"

        class ArticleType(DjangoObjectType):
            class Meta:
                model = Article
                fields = "__all__"

        class PetMutation(DjangoCreateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', 'age')

        class FilmMutation(DjangoCreateModelMutation):
            class Meta:
                model = Film
                fields = ('genre', 'reporters', 'jacket_image', 'data', 'extra_data')

        class FilmDetailsMutation(DjangoCreateModelMutation):
            class Meta:
                model = FilmDetails
                fields = ('location', 'film')

        class ReporterMutation(DjangoCreateModelMutation):
            class Meta:
                model = Reporter
                fields = ('first_name', 'last_name', 'email', 'reporter_type')

        class ArticleMutation(DjangoCreateModelMutation):
            class Meta:
                model = Article
                fields = ('headline', 'pub_date', 'pub_date_time', 'reporter', 'editor', 'lang', 'importance', )


        class Mutation(ObjectType):
            pet_mutation = PetMutation.Field()
            film_mutation = FilmMutation.Field()
            filmdetails_mutation = FilmDetailsMutation.Field()
            reporter_mutation = ReporterMutation.Field()
            article_mutation = ArticleMutation.Field()

        self.schema = Schema(mutation=Mutation)

    def teardown_method(self, method):
        reset_global_registry()

    def test_basic(self):
        schema_str = str(Schema(types=[self.schema.get_type('PetMutationInput')]))
        self.assertEqual(schema_str, '''schema {

}

input PetMutationInput {
  name: String!
  age: Int!
  formPrefix: String
  clientMutationId: String
}
''')
        result = self.schema.execute(
            """ mutation PetMutation {
                petMutation(input: { name: "Mia", age: 10 }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """
        )

        self.assertIs(result.errors, None)

        data = result.data['petMutation']
        self.assertEqual(data['errors'], [])
        self.assertEqual(data["pet"], {"name": "Mia", "age": 10})

        self.assertEqual(Pet.objects.count(), 1)
        pet = Pet.objects.get()
        self.assertEqual(pet.name, "Mia")
        self.assertEqual(pet.age, 10)

    def test_one_to_one(self):
        schema_str = str(Schema(types=[self.schema.get_type('FilmDetailsMutationInput')]))
        self.assertEqual(schema_str, '''schema {

}

input FilmDetailsMutationInput {
  location: String!
  film: ID!
  formPrefix: String
  clientMutationId: String
}
''')

        film = Film.objects.create(genre='do')
        result = self.schema.execute(
            """ mutation PetMutation($film: ID!) {
                filmdetailsMutation(input: { location: "tokyo", film: $film }) {
                    errors {
                        field
                        messages
                    }
                    filmDetails {
                        location
                        film {
                            id
                            genre
                        }
                    }
                }
            }
            """,
            variable_values={"film": to_global_id('FilmType', film.pk)}
        )
        # print(result.errors)
        # print(result.data)
        self.assertIs(result.errors, None)
        data = result.data['filmdetailsMutation']
        self.assertEqual(data['errors'], [])
        self.assertEqual(data["filmDetails"], {
            'location': 'tokyo',
            'film': {'id': to_global_id('FilmType', film.pk), 'genre': 'DO'}})

        self.assertEqual(FilmDetails.objects.count(), 1)
        film_details = FilmDetails.objects.get()
        self.assertEqual(film_details.location, "tokyo")
        self.assertEqual(film_details.film.pk, film.pk)


    def test_many(self):
        schema_str = str(Schema(types=[self.schema.get_type('FilmMutationInput')]))
        # print(schema_str)
        self.assertEqual(schema_str, '''schema {

}

enum FilmGenre {
  DO
  OT
}

input FilmMutationInput {
  genre: FilmGenre!
  reporters: [ID]!
  jacketImage: Upload
  data: Upload!
  extraData: String!
  formPrefix: String
  clientMutationId: String
}

scalar Upload
''')

        reporter = Reporter.objects.create(first_name="John")

        fio = io.BytesIO()
        fio.write(b'hello world')
        fio.seek(0)

        bio = io.BytesIO()
        img = Image.new('RGB', (16, 8))
        img.save(bio, format='png')
        bio.seek(0)

        txt_filename = '{}.txt'.format(uuid.uuid4().hex)
        png_filename = '{}.png'.format(uuid.uuid4().hex)
        
        class CTX: pass
        context = CTX()
        context.FILES = MultiValueDict()
        context.FILES['jacketImage'] = SimpleUploadedFile(png_filename, bio.getvalue())
        context.FILES['data'] = SimpleUploadedFile(txt_filename, fio.getvalue())

        result = self.schema.execute(
            """ mutation AnyNameHere($input: FilmMutationInput!) {
                filmMutation(input: $input) {
                    errors {
                        field
                        messages
                    }
                    film {
                        genre
                        reporters {
                            edges {
                                node {
                                    id
                                    firstName
                                }
                            }
                        }
                        jacketImage {
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
            """,
            variable_values={"input": {
                "genre": "DO",
                "reporters": [to_global_id('ReporterType', reporter.pk)],
                "jacketImage": "",
                "data": "",
                "extraData": "Zm9v",
            }},
            context_value=context,
        )
        # print(result.errors)
        # print(result.data)
        self.assertIs(result.errors, None)
        data = result.data['filmMutation']
        self.assertEqual(data['errors'], [])
        self.assertEqual(data["film"],
                         {'data': {'data': 'aGVsbG8gd29ybGQ=',
                                   'name': 'tmp/film/data/{}'.format(txt_filename),
                                   'size': 11,
                                   'url': 'tmp/film/data/{}'.format(txt_filename)},
                          'extraData': 'Zm9v',
                          'genre': 'DO',
                          'jacketImage': {'height': 8,
                                     'name': 'tmp/film/jacket/{}'.format(png_filename),
                                     'size': 71,
                                     'url': 'tmp/film/jacket/{}'.format(png_filename),
                                     'width': 16},
                          'reporters': {'edges': [{'node': {'firstName': 'John',
                                                            'id': to_global_id('ReporterType', reporter.pk)}}]}})
        self.assertEqual(Film.objects.count(), 1)
        film = Film.objects.get()
        self.assertEqual(film.reporters.all().count(), 1)
        self.assertEqual(film.reporters.all()[0], reporter)
        self.assertEqual(film.extra_data, b'foo')

        film.data.delete()
        film.jacket_image.delete()

    def test_many_prefix(self):
        schema_str = str(Schema(types=[self.schema.get_type('FilmMutationInput')]))
        # print(schema_str)
        self.assertEqual(schema_str, '''schema {

}

enum FilmGenre {
  DO
  OT
}

input FilmMutationInput {
  genre: FilmGenre!
  reporters: [ID]!
  jacketImage: Upload
  data: Upload!
  extraData: String!
  formPrefix: String
  clientMutationId: String
}

scalar Upload
''')

        reporter = Reporter.objects.create(first_name="John")

        fio = io.BytesIO()
        fio.write(b'hello world')
        fio.seek(0)

        bio = io.BytesIO()
        img = Image.new('RGB', (16, 8))
        img.save(bio, format='png')
        bio.seek(0)

        txt_filename = '{}.txt'.format(uuid.uuid4().hex)
        png_filename = '{}.png'.format(uuid.uuid4().hex)

        prefix = 'hello'

        class CTX: pass
        context = CTX()
        context.FILES = MultiValueDict()
        context.FILES['{}-jacketImage'.format(prefix)] = SimpleUploadedFile(png_filename, bio.getvalue())
        context.FILES['{}-data'.format(prefix)] = SimpleUploadedFile(txt_filename, fio.getvalue())

        result = self.schema.execute(
            """ mutation AnyNameHere($input: FilmMutationInput!) {
                filmMutation(input: $input) {
                    errors {
                        field
                        messages
                    }
                    film {
                        genre
                        reporters {
                            edges {
                                node {
                                    id
                                    firstName
                                }
                            }
                        }
                        jacketImage {
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
            """,
            variable_values={"input": {
                "genre": "DO",
                "reporters": [to_global_id('ReporterType', reporter.pk)],
                "jacketImage": "",
                "data": "",
                "extraData": "Zm9v",
                "formPrefix": prefix,
            }},
            context_value=context,
        )
        # print(prefix)
        # print(result.errors)
        # print(result.data)
        self.assertIs(result.errors, None)
        data = result.data['filmMutation']
        self.assertEqual(data['errors'], [])
        self.assertEqual(data["film"],
                         {'data': {'data': 'aGVsbG8gd29ybGQ=',
                                   'name': 'tmp/film/data/{}'.format(txt_filename),
                                   'size': 11,
                                   'url': 'tmp/film/data/{}'.format(txt_filename)},
                          'extraData': 'Zm9v',
                          'genre': 'DO',
                          'jacketImage': {'height': 8,
                                     'name': 'tmp/film/jacket/{}'.format(png_filename),
                                     'size': 71,
                                     'url': 'tmp/film/jacket/{}'.format(png_filename),
                                     'width': 16},
                          'reporters': {'edges': [{'node': {'firstName': 'John',
                                                            'id': to_global_id('ReporterType', reporter.pk)}}]}})
        self.assertEqual(Film.objects.count(), 1)
        film = Film.objects.get()
        self.assertEqual(film.reporters.all().count(), 1)
        self.assertEqual(film.reporters.all()[0], reporter)
        self.assertEqual(film.extra_data, b'foo')

        film.data.delete()
        film.jacket_image.delete()


@pytest.mark.django_db
class ChoiceMutationTests(TestCase):
    def setup_method(self, method):
        class ReporterType(DjangoObjectType):
            class Meta:
                model = Reporter
                fields = ("reporter_type", )

        class ReporterMutation(DjangoCreateModelMutation):
            class Meta:
                model = Reporter
                fields = ('reporter_type', )

        class ReportForm(GrapheneModelForm):
            class Meta:
                model = Reporter
                fields = ("reporter_type", )

        class ReporterFormMutation(DjangoCreateModelMutation):
            class Meta:
                form_class = ReportForm

        class Mutation(ObjectType):
            reporter_mutation = ReporterMutation.Field()
            reporter_form_mutation = ReporterFormMutation.Field()

        self.schema = Schema(mutation=Mutation)


    def test_film_choices(self):
        schema_str = str(Schema(types=[self.schema.get_type('ReporterMutationInput')]))
        self.assertEqual(schema_str, '''schema {

}

input ReporterMutationInput {
  reporterType: ReporterReporterType
  formPrefix: String
  clientMutationId: String
}

enum ReporterReporterType {
  A_1
  A_2
}
''')

        result = self.schema.execute('''
        mutation ReporterMutation($input: ReporterMutationInput!) {
          reporterMutation(input: $input) {
            errors {
              field
              messages
            }
            reporter {
              reporterType
            }
          }
        }
        ''', variable_values={"input": {
            "reporterType": "A_1",
        }})
        assert result.errors == None
        assert result.data['reporterMutation']['reporter'] == {'reporterType': 'A_1'}


    def test_film_choices_form(self):
        schema_str = str(Schema(types=[self.schema.get_type('ReporterFormMutationInput')]))
        self.assertEqual(schema_str, '''schema {

}

input ReporterFormMutationInput {
  reporterType: ReporterReporterType
  formPrefix: String
  clientMutationId: String
}

enum ReporterReporterType {
  A_1
  A_2
}
''')

        result = self.schema.execute('''
        mutation ReporterFormMutation($input: ReporterFormMutationInput!) {
          reporterFormMutation(input: $input) {
            errors {
              field
              messages
            }
            reporter {
              reporterType
            }
          }
        }
        ''', variable_values={"input": {
            "reporterType": "A_1",
        }})
        assert result.errors == None
        assert result.data['reporterFormMutation']['reporter'] == {'reporterType': 'A_1'}
    

    def test_film_choices_form_none(self):
        schema_str = str(Schema(types=[self.schema.get_type('ReporterFormMutationInput')]))
        self.assertEqual(schema_str, '''schema {

}

input ReporterFormMutationInput {
  reporterType: ReporterReporterType
  formPrefix: String
  clientMutationId: String
}

enum ReporterReporterType {
  A_1
  A_2
}
''')

        result = self.schema.execute('''
        mutation ReporterFormMutation($input: ReporterFormMutationInput!) {
          reporterFormMutation(input: $input) {
            errors {
              field
              messages
            }
            reporter {
              reporterType
            }
          }
        }
        ''', variable_values={"input": {
            "reporterType": None,
        }})
        assert result.errors == None
        assert result.data['reporterFormMutation']['reporter'] == {'reporterType': None}
    

@pytest.mark.django_db
class GetOrCreateModelMutationTests(TestCase):
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = Pet
                fields = "__all__"

        class ReporterType(DjangoObjectType):
            class Meta:
                model = Reporter
                fields = ('first_name', )

        class PetGetOrCreate(DjangoGetOrCreateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', 'age', )

        class PetGetOrCraeteForm(forms.ModelForm):
            class Meta:
                model = Pet
                fields = ('age', )

            def save(self):
                self.instance.name = 'default-name'
                return super().save()

        class PetGetOrCreateForm(DjangoGetOrCreateModelMutation):
            class Meta:
                model = Pet
                form_class = PetGetOrCraeteForm

        class PetGetOrCreateForeignKey(DjangoGetOrCreateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', 'age', 'reporter', )

        class PetGetOrCraeteFormForeignKey(forms.ModelForm):
            class Meta:
                model = Pet
                fields = ('reporter', )

            def save(self):
                self.instance.name = 'default-name'
                self.instance.age = 0
                return super().save()

        class PetGetOrCreateFormForeignKey(DjangoGetOrCreateModelMutation):
            class Meta:
                model = Pet
                form_class = PetGetOrCraeteFormForeignKey

        class Mutation(ObjectType):
            pet_get_or_create = PetGetOrCreate.Field()
            pet_get_or_create_form = PetGetOrCreateForm.Field()
            pet_get_or_create_foreign_key = PetGetOrCreateForeignKey.Field()
            pet_get_or_create_form_foreign_key = PetGetOrCreateFormForeignKey.Field()

        self.PetType = PetType
        self.schema = Schema(mutation=Mutation)

    def teardown_method(self, method):
        reset_global_registry()

    def test_create(self):
        assert Pet.objects.all().count() == 0
        result = self.schema.execute(
            """ mutation {
            petGetOrCreate(input: { name: "Mia", age: 10 }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())
        assert result.errors is None
        assert result.data['petGetOrCreate']['pet'] == {'name': 'Mia', 'age': 10}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'Mia'
        assert Pet.objects.get().age == 10

    def test_get(self):
        Pet.objects.create(name="Mia", age=10)
        assert Pet.objects.all().count() == 1
        result = self.schema.execute(
            """ mutation {
            petGetOrCreate(input: { name: "Mia", age: 10 }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())
        assert result.errors is None
        assert result.data['petGetOrCreate']['pet'] == {'name': 'Mia', 'age': 10}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'Mia'
        assert Pet.objects.get().age == 10

    def test_create_form(self):
        Pet.objects.create(name="Mia", age=0)
        assert Pet.objects.all().count() == 1
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateForm(input: { age: 10 }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())
        assert result.errors is None
        assert result.data['petGetOrCreateForm']['pet'] == {'name': 'default-name', 'age': 10}
        assert Pet.objects.all().count() == 2
        assert Pet.objects.get(age=10).name == 'default-name'
        assert Pet.objects.get(age=10).age == 10

    def test_get_form(self):
        Pet.objects.create(name="Mia", age=10)
        assert Pet.objects.all().count() == 1
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateForm(input: { age: 10 }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())
        assert result.errors is None
        assert result.data['petGetOrCreateForm']['pet'] == {'name': 'Mia', 'age': 10}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'Mia'
        assert Pet.objects.get().age == 10

    def test_create_foreign_key(self):
        reporter = Reporter.objects.create(first_name="John")
        assert Pet.objects.all().count() == 0
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateForeignKey(input: { name: "Mia", age: 10, reporter: "%s" }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                        reporter {
                            firstName
                        }
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """ % to_global_id("ReporterType", reporter.pk)
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())

        assert result.errors is None
        assert result.data['petGetOrCreateForeignKey']['pet'] == {'name': 'Mia', 'age': 10, 'reporter': {'firstName': 'John'}}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'Mia'
        assert Pet.objects.get().age == 10
        assert Pet.objects.get().reporter == reporter

    def test_get_foreign_key(self):
        reporter = Reporter.objects.create(first_name="John")
        Pet.objects.create(name="Mia", age=10, reporter=reporter)
        assert Pet.objects.all().count() == 1
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateForeignKey(input: { name: "Mia", age: 10, reporter: "%s" }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                        reporter {
                            firstName
                        }
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """ % to_global_id("ReporterType", reporter.pk)
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())
        assert result.errors is None
        assert result.data['petGetOrCreateForeignKey']['pet'] == {'name': 'Mia', 'age': 10, 'reporter': {'firstName': 'John'}}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'Mia'
        assert Pet.objects.get().age == 10
        assert Pet.objects.get().reporter == reporter

    def test_get_foreign_key_error(self):
        assert Pet.objects.all().count() == 0
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateForeignKey(input: { name: "Mia", age: 10, reporter: "%s" }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                        reporter {
                            firstName
                        }
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """ % "no-value"
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        assert result.errors is None
        assert len(result.data['petGetOrCreateForeignKey']['errors']) == 1
        assert result.data['petGetOrCreateForeignKey']['pet'] is None
        assert Pet.objects.all().count() == 0


    def test_create_form_foreign_key(self):
        reporter = Reporter.objects.create(first_name="John")
        assert Pet.objects.all().count() == 0
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateFormForeignKey(input: { reporter: "%s" }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                        reporter {
                            firstName
                        }
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """ % to_global_id("ReporterType", reporter.pk)
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())

        assert result.errors is None
        assert result.data['petGetOrCreateFormForeignKey']['pet'] == {'name': 'default-name', 'age': 0, 'reporter': {'firstName': 'John'}}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'default-name'
        assert Pet.objects.get().age == 0
        assert Pet.objects.get().reporter == reporter

    def test_get_form_foreign_key(self):
        reporter = Reporter.objects.create(first_name="John")
        Pet.objects.create(name="Mia", age=10, reporter=reporter)
        assert Pet.objects.all().count() == 1
        result = self.schema.execute(
            """ mutation {
            petGetOrCreateFormForeignKey(input: { reporter: "%s" }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        name
                        age
                        reporter {
                            firstName
                        }
                    }
                    edge {
                        cursor
                        node {
                            id
                        }
                    }
                }
            }
            """ % to_global_id("ReporterType", reporter.pk)
        )
        # print(result.errors)
        # print(result.data)
        # print(Pet.objects.all().count())
        # print(Pet.objects.get())
        assert result.errors is None
        assert result.data['petGetOrCreateFormForeignKey']['pet'] == {'name': 'Mia', 'age': 10, 'reporter': {'firstName': 'John'}}
        assert Pet.objects.all().count() == 1
        assert Pet.objects.get().name == 'Mia'
        assert Pet.objects.get().age == 10
        assert Pet.objects.get().reporter == reporter



@pytest.mark.django_db
class UpdateModelMutationTests(TestCase):
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = Pet
                fields = "__all__"

        class FilmType(DjangoObjectType):
            class Meta:
                model = Film
                fields = "__all__"

        class FilmDetailsType(DjangoObjectType):
            class Meta:
                model = FilmDetails
                fields = "__all__"

        class ReporterType(DjangoObjectType):
            class Meta:
                model = Reporter
                fields = "__all__"

        class ArticleType(DjangoObjectType):
            class Meta:
                model = Article
                fields = "__all__"

        class PetMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', 'age')

        class FilmMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Film
                fields = ('genre', 'reporters', 'jacket_image', 'data', 'extra_data')

        class FilmDetailsMutation(DjangoUpdateModelMutation):
            class Meta:
                model = FilmDetails
                fields = ('location', 'film')

        class ReporterMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Reporter
                fields = ('first_name', 'last_name', 'email', 'pets', 'a_choice', )

        class ArticleMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Article
                fields = ('headline', 'pub_date', 'pub_date_time', 'reporter', 'editor', 'lang', 'importance', )


        class Mutation(ObjectType):
            pet_mutation = PetMutation.Field()
            film_mutation = FilmMutation.Field()
            filmdetails_mutation = FilmDetailsMutation.Field()
            reporter_mutation = ReporterMutation.Field()
            article_mutation = ArticleMutation.Field()

        self.schema = Schema(mutation=Mutation)

    def teardown_method(self, method):
        reset_global_registry()

    def test_basic(self):
        schema_str = str(Schema(types=[self.schema.get_type('PetMutationInput')]))
        # print(schema_str)
        self.assertEqual(schema_str, '''schema {

}

input PetMutationInput {
  name: String
  age: Int
  id: ID!
  formPrefix: String
  clientMutationId: String
}
''')
        pet = Pet.objects.create(name='name', age=0)
        result = self.schema.execute(
            """ mutation($pk: ID!, $name: String!) {
                petMutation(input: { id: $pk, name: $name }) {
                    errors {
                        field
                        messages
                    }
                    pet {
                        id
                        name
                        age
                    }
                }
            }
            """,
            variable_values={"pk": to_global_id('PetType', pet.pk), 'name': 'new-name'},
        )

        # print(result.errors)
        # print(result.data)
        assert not result.errors
        assert result.data == {'petMutation': {'errors': [], 'pet': {'id': to_global_id('PetType', pet.pk), 'name': 'new-name', 'age': 0}}}
        

    def test_one_to_one(self):
        schema_str = str(Schema(types=[self.schema.get_type('FilmDetailsMutationInput')]))
        self.assertEqual(schema_str, '''schema {

}

input FilmDetailsMutationInput {
  location: String
  film: ID
  id: ID!
  formPrefix: String
  clientMutationId: String
}
''')

        film = Film.objects.create(genre='do')
        film_details = FilmDetails.objects.create(location='Tokyo', film=film)
        
        result = self.schema.execute(
            """ mutation($pk: ID!) {
                filmdetailsMutation(input: { id: $pk, location: "tokyo" }) {
                    errors {
                        field
                        messages
                    }
                    filmDetails {
                        location
                        film {
                            id
                            genre
                        }
                    }
                }
            }
            """,
            variable_values={"pk": to_global_id('FilmDetailsType', film_details.pk)}
        )
        # print(result.errors)
        # print(result.data)
        self.assertIs(result.errors, None)
        data = result.data['filmdetailsMutation']
        self.assertEqual(data['errors'], [])
        self.assertEqual(data["filmDetails"], {
            'location': 'tokyo',
            'film': {'id': to_global_id('FilmType', film.pk), 'genre': 'DO'}})

        self.assertEqual(FilmDetails.objects.count(), 1)
        film_details = FilmDetails.objects.get()
        self.assertEqual(film_details.location, "tokyo")
        self.assertEqual(film_details.film.pk, film.pk)

    def test_one_to_one_update(self):
        film0 = Film.objects.create(genre='do')
        film1 = Film.objects.create(genre='ot')
        film_details = FilmDetails.objects.create(location='Tokyo', film=film0)
        
        result = self.schema.execute(
            """ mutation($pk: ID!, $film: ID) {
                filmdetailsMutation(input: { id: $pk, location: "tokyo", film: $film }) {
                    errors {
                        field
                        messages
                    }
                    filmDetails {
                        location
                        film {
                            id
                            genre
                        }
                    }
                }
            }
            """,
            variable_values={
                "pk": to_global_id('FilmDetailsType', film_details.pk),
                "film": to_global_id('FilmType', film1.pk),
            }
        )
        # print(result.errors)
        # print(result.data)
        self.assertIs(result.errors, None)
        data = result.data['filmdetailsMutation']
        self.assertEqual(data['errors'], [])
        self.assertEqual(data["filmDetails"], {
            'location': 'tokyo',
            'film': {'id': to_global_id('FilmType', film1.pk), 'genre': 'OT'}})

        self.assertEqual(FilmDetails.objects.count(), 1)
        film_details = FilmDetails.objects.get()
        self.assertEqual(film_details.location, "tokyo")
        self.assertEqual(film_details.film.pk, film1.pk)

    def test_one_to_one_clear(self):
        film = Film.objects.create(genre='do')
        film_details = FilmDetails.objects.create(location='Tokyo', film=film)
        
        result = self.schema.execute(
            """ mutation($pk: ID!, $film: ID) {
                filmdetailsMutation(input: { id: $pk, film: $film }) {
                    errors {
                        field
                        messages
                    }
                    filmDetails {
                        location
                        film {
                            id
                            genre
                        }
                    }
                }
            }
            """,
            variable_values={"pk": to_global_id('FilmDetailsType', film_details.pk), "film": None}
        )
        self.assertIs(result.errors, None)
        data = result.data['filmdetailsMutation']
        self.assertEqual(data['errors'], [{'field': 'film', 'messages': ['This field is required.']}])


    def test_file(self):
        # TODO: clear file
        schema_str = str(Schema(types=[self.schema.get_type('FilmMutationInput')]))
        # print(schema_str)
        self.assertEqual(schema_str, '''schema {

}

enum FilmGenre {
  DO
  OT
}

input FilmMutationInput {
  genre: FilmGenre
  reporters: [ID]
  jacketImage: Upload
  data: Upload
  extraData: String
  id: ID!
  formPrefix: String
  clientMutationId: String
}

scalar Upload
''')

        txt_filename = '{}.txt'.format(uuid.uuid4().hex)
        png_filename = '{}.png'.format(uuid.uuid4().hex)

        try:
            f = Film.objects.create()

            f.data.save(txt_filename, ContentFile(b'foo'), save=True)

            bio = io.BytesIO()
            img = Image.new('RGB', (16, 8))
            img.save(bio, format='png')
            f.jacket_image.save(png_filename, ContentFile(bio.getvalue()), save=True)

            f.extra_data = b'foo'
            f.save()

            result = self.schema.execute(
                """ mutation($input: FilmMutationInput!) {
                    filmMutation(input: $input) {
                        errors {
                            field
                            messages
                        }
                        film {
                            jacketImage {
                                name
                            }
                            data {
                                name
                            }
                        }
                    }
                }
                """,
                variable_values={"input": {
                    "id": to_global_id('FilmType', f.pk),
                    "jacketImage": None,
                }},
            )
            # print(result.errors)
            # print(result.data)
            self.assertIs(result.errors, None)
            self.assertEqual(result.data['filmMutation'],
                             {'errors': [], 'film': {
                                 'jacketImage': {'name': 'tmp/film/jacket/{}'.format(png_filename)},
                                 'data': {'name': 'tmp/film/data/{}'.format(txt_filename)}}})
            f.data.delete()
            f.jacket_image.delete()
        finally:
            txt_filename = os.path.join('tmp/film/data', txt_filename)
            png_filename = os.path.join('tmp/film/jacket', png_filename)
            if os.path.exists(txt_filename):
                os.remove(txt_filename)
            if os.path.exists(png_filename):
                os.remove(png_filename)
        

    def test_many_to_many(self):
        f = Film.objects.create()
        reporter0 = Reporter.objects.create(first_name="John")
        reporter1 = Reporter.objects.create(first_name="Dan")
        f.reporters.add(reporter0)
        f.save()
        

        result = self.schema.execute(
            """ mutation($input: FilmMutationInput!) {
                filmMutation(input: $input) {
                    errors {
                        field
                        messages
                    }
                    film {
                        reporters {
                            edges {
                                node {
                                    id
                                    firstName
                                }
                            }
                        }
                    }
                }
            }
            """,
            variable_values={"input": {
                "id": to_global_id('FilmType', f.pk),
                "reporters": [to_global_id('ReporterType', reporter1.pk)],
            }},
        )

        # print(result.errors)
        # print(result.data)
        self.assertIs(result.errors, None)
        self.assertEqual(result.data['filmMutation'],
                         {'errors': [], 'film': {
                             'reporters': {'edges': [{'node': {
                                 'id': to_global_id('ReporterType', reporter1.pk),
                                 'firstName': 'Dan'}}]}}})


@pytest.mark.django_db
class DeleteModelMutationTests(TestCase):
    def setup_method(self, method):
        class PetType(DjangoObjectType):
            class Meta:
                model = Pet
                fields = "__all__"

    def teardown_method(self, method):
        reset_global_registry()


    def test_model_delete_mutation(self):
        pet = Pet.objects.create(name='name', age=0)

        class PetMutation(DjangoDeleteModelMutation):
            class Meta:
                model = Pet

        class Mutation(ObjectType):
            pet_delete = PetMutation.Field()

        schema = Schema(mutation=Mutation)

        result = schema.execute(
            """ mutation PetMutation($pk: ID!) {
                petDelete(input: { id: $pk }) {
                    deletedId
                }
            }
            """,
            variable_values={"pk": to_global_id('PetType', pet.pk)},
        )

        assert not result.errors
        assert result.data == {'petDelete': {'deletedId': 'UGV0VHlwZTox'}}
        assert Pet.objects.all().count() == 0


    def test_model_delete_mutation_fail(self):
        class PetMutation(DjangoDeleteModelMutation):
            class Meta:
                model = Pet

        class Mutation(ObjectType):
            pet_delete = PetMutation.Field()

        schema = Schema(mutation=Mutation)

        result = schema.execute(
            """ mutation PetMutation($pk: ID!) {
                petDelete(input: { id: $pk }) {
                    errors {
                        field
                        messages
                    }
                    deletedId
                }
            }
            """,
            variable_values={"pk": to_global_id('PetType', 0)},
        )
        # print(result.errors)
        # print(result.data)
        assert not result.errors
        assert result.data == {'petDelete': {'errors': [{'field': '_All__', 'messages': ['Select a valid choice. That choice is not one of the available choices.']}], 'deletedId': None}}


    def test_model_delete_mutation_form(self):
        pet = Pet.objects.create(name='name', age=0)

        class PetDeleteForm(forms.ModelForm):
            class Meta:
                model = Pet
                fields = ()

            def save(self):
                gid = to_global_id('PetType', self.instance.pk)
                self.instance.delete()
                return gid

        class PetMutation(DjangoDeleteModelMutation):
            class Meta:
                form_class = PetDeleteForm

        class Mutation(ObjectType):
            pet_delete = PetMutation.Field()

        schema = Schema(mutation=Mutation)

        result = schema.execute(
            """ mutation PetMutation($pk: ID!) {
                petDelete(input: { id: $pk }) {
                    deletedId
                }
            }
            """,
            variable_values={"pk": to_global_id('PetType', pet.pk)},
        )

        assert not result.errors
        assert result.data == {'petDelete': {'deletedId': 'UGV0VHlwZTox'}}
        assert Pet.objects.all().count() == 0



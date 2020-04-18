import pytest
import io
from PIL import Image
import uuid

from django import forms
from django.test import TestCase
from django.core.exceptions import ValidationError
from py.test import raises

from graphene import ObjectType, Schema, String, Field
from graphene_django import DjangoObjectType
from graphene_django.tests.models import Film, FilmDetails, Pet, Reporter, Article

from graphql_relay import to_global_id


from ...settings import graphene_settings
from ..mutation import (
    DjangoFormMutation,
    DjangoCreateModelMutation,
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
    assert {f.field for f in result.errors} == {"name", "age", "test_field"}
    graphene_settings.CAMELCASE_ERRORS = True
    result = PetMutation.mutate_and_get_payload(None, None)
    assert {f.field for f in result.errors} == {"name", "age", "testField"}
    graphene_settings.CAMELCASE_ERRORS = False



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

    def test_default_update_input_meta_fields_auto_gen_execute(self):
        pet = Pet.objects.create(name='name', age=0)

        class PetMutation(DjangoUpdateModelMutation):
            class Meta:
                model = Pet
                fields = ('name', 'age')

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

        print(result.errors)
        print(result.data)
        assert not result.errors
        assert result.data == {'petUpdate': {'errors': [], 'pet': {'id': 'UGV0VHlwZTox', 'name': 'new-name', 'age': 0}}}


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
                fields = ('genre', 'reporters', 'jacket', 'data', 'extra_data')

        class FilmDetailsMutation(DjangoCreateModelMutation):
            class Meta:
                model = FilmDetails
                fields = ('location', 'film')

        class ReporterMutation(DjangoCreateModelMutation):
            class Meta:
                model = Reporter
                fields = ('first_name', 'last_name', 'email', 'pets', 'a_choice', )

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

input FilmMutationInput {
  genre: String!
  reporters: [ID]!
  jacket: Upload!
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
        
        class CTX:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        from django.core.files.uploadedfile import SimpleUploadedFile
        context = CTX()
        context.FILES = {
            # 'jacket': CTX(name='img.png', size=len(bio.getvalue()), read=lambda : bio.getvalue(), _committed=True),
            # 'data': CTX(name='hello.txt', size=len(fio.getvalue()), read=lambda : fio.getvalue(), _committed=True),
            'jacket': SimpleUploadedFile(png_filename, bio.getvalue()),
            'data': SimpleUploadedFile(txt_filename, fio.getvalue()),
        }

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
            """,
            variable_values={"input": {
                "genre": "do",
                "reporters": [to_global_id('ReporterType', reporter.pk)],
                "jacket": "",
                "data": "",
                "extraData": "Zm9v",
            }},
            context_value=context,
        )
        print(result.errors)
        print(result.data)
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
                          'jacket': {'height': 8,
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
            variable_values={"pk": to_global_id('PetType', 1)},
        )

        assert not result.errors
        assert result.data == {'petDelete': {'errors': [{'field': 'id', 'messages': ['no id found']}], 'deletedId': None}}

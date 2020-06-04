from django import forms
from django.core.exceptions import ImproperlyConfigured

from graphene import ID, Boolean, Float, Int, List, String, UUID, Date, DateTime, Time

from .forms import GlobalIDFormField, GlobalIDMultipleChoiceField
from ..utils import import_single_dispatch
from ..types import Upload
from ..converter import convert_choices_to_named_enum_with_descriptions


singledispatch = import_single_dispatch()


@singledispatch
def convert_form_field(field, force_required_false=False):
    raise ImproperlyConfigured(
        "Don't know how to convert the Django form field %s (%s) "
        "to Graphene type" % (field, field.__class__)
    )


# @convert_form_field.register(forms.TypedChoiceField)
# def covnert_form_field_to_enum(field, force_required_false=False):
#     print(field)
#     print(dir(field))
#     enum = convert_choices_to_named_enum_with_descriptions(name, field.choices)
#     pass


@convert_form_field.register(forms.fields.BaseTemporalField)
@convert_form_field.register(forms.CharField)
@convert_form_field.register(forms.EmailField)
@convert_form_field.register(forms.SlugField)
@convert_form_field.register(forms.URLField)
@convert_form_field.register(forms.ChoiceField)
@convert_form_field.register(forms.RegexField)
@convert_form_field.register(forms.Field)
def convert_form_field_to_string(field, force_required_false=False):
    return String(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.UUIDField)
def convert_form_field_to_uuid(field, force_required_false=False):
    return UUID(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.IntegerField)
@convert_form_field.register(forms.NumberInput)
def convert_form_field_to_int(field, force_required_false=False):
    return Int(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.BooleanField)
def convert_form_field_to_boolean(field, force_required_false=False):
    return Boolean(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.NullBooleanField)
def convert_form_field_to_nullboolean(field, force_required_false=False):
    return Boolean(description=field.help_text)


@convert_form_field.register(forms.DecimalField)
@convert_form_field.register(forms.FloatField)
def convert_form_field_to_float(field, force_required_false=False):
    return Float(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.ModelMultipleChoiceField)
@convert_form_field.register(GlobalIDMultipleChoiceField)
def convert_form_field_to_list(field, force_required_false=False):
    return List(ID, required=(not force_required_false) and field.required)

@convert_form_field.register(forms.DateField)
def convert_form_field_to_date(field, force_required_false=False):
    return Date(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.DateTimeField)
def convert_form_field_to_datetime(field, force_required_false=False):
    return DateTime(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.TimeField)
def convert_form_field_to_time(field, force_required_false=False):
    return Time(description=field.help_text, required=(not force_required_false) and field.required)


@convert_form_field.register(forms.ModelChoiceField)
@convert_form_field.register(GlobalIDFormField)
def convert_form_field_to_id(field, force_required_false=False):
    return ID(required=(not force_required_false) and field.required)


@convert_form_field.register(forms.FileField)
@convert_form_field.register(forms.ImageField)
def convert_form_field_to_upload(field, force_required_false=False):
    return Upload(description=field.help_text, required=(not force_required_false) and field.required)


class ModelToFormChoiceField(forms.TypedChoiceField):

    def __init__(self, model, field_name, *args, **kwargs):
        self._model = model
        self.parent_field = model._meta.get_field(field_name)
        super().__init__(choices=self.parent_field.choices, empty_value=None, *args, **kwargs)


@convert_form_field.register(ModelToFormChoiceField)
def convert_form_field_to_int_2(field, force_required_false=False):
    from graphene_django.converter import convert_django_field_with_choices
    from graphene_django.registry import get_global_registry
    registry = get_global_registry()
    enum_type = type(convert_django_field_with_choices(field.parent_field, registry))
    return enum_type(required=(not force_required_false) and field.required)

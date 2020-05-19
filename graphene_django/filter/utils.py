import itertools
import six

from django_filters import OrderingFilter
from django_filters.utils import get_model_field
from .filterset import custom_filterset_factory, setup_filterset

from django import forms
from django.db import models
import graphene
from graphene_django.forms.converter import convert_form_field
from graphene_django.converter import convert_django_field_with_choices
from graphene_django.registry import get_global_registry
from graphene_django.forms import GlobalIDFormField, GlobalIDMultipleChoiceField


class MultipleOrderingFilter(OrderingFilter):
    max_conbination = 3

    def filter(self, qs, value):
        if value:
            value = sum((y for y in (x.split(',') for x in value) if y), [])
        return super().filter(qs, value)

    def build_choices(self, fields, labels):
        choices = super().build_choices(fields, labels)
        multiple_choices = []
        for i in range(2, min(len(choices) + 1, self.max_conbination)):
            for j in itertools.permutations(choices, i):
                s = set()
                ok = True
                for field, disp in j:
                    if field.startswith('-'):
                        field = field[1:]
                    if field in s:
                        ok = False
                        break
                    s.add(field)

                if ok:
                    multiple_choices.append((
                        ','.join([field for field, _ in j]),
                        ','.join([str(disp) for _, disp in j])))

        return choices + multiple_choices


class ModelToFormChoiceField(forms.ChoiceField):
    def __init__(self, model, field_name, *args, **kwargs):
        self._model = model
        self.parent_field = model._meta.get_field(field_name)
        super().__init__(choices=self.parent_field.choices, *args, **kwargs)


class ModelToFormMultipleChoiceField(forms.MultipleChoiceField):
    def __init__(self, model, field_name, *args, **kwargs):
        self._model = model
        self.parent_field = model._meta.get_field(field_name)
        super().__init__(choices=self.parent_field.choices, *args, **kwargs)


@convert_form_field.register(ModelToFormChoiceField)
def convert_form_field_to_int(field, force_required_false=False):
    registry = get_global_registry()
    enum = convert_django_field_with_choices(field.parent_field, registry)
    return type(enum)(required=False)


@convert_form_field.register(ModelToFormMultipleChoiceField)
def convert_form_field_to_int_multiple(field, force_required_false=False):
    registry = get_global_registry()
    enum = convert_django_field_with_choices(field.parent_field, registry)
    return graphene.List(type(enum), required=False)


def get_filtering_args_from_filterset(filterset_class, type):
    """ Inspect a FilterSet and produce the arguments to pass to
        a Graphene Field. These arguments will be available to
        filter against in the GraphQL
    """
    from ..forms.converter import convert_form_field

    args = {}
    model = filterset_class._meta.model
    for name, filter_field in six.iteritems(filterset_class.base_filters):
        form_field = None

        if name in filterset_class.declared_filters:
            form_field = filter_field.field
        else:
            model_field = get_model_field(model, filter_field.field_name)

            filter_type = filter_field.lookup_expr
            if filter_type != "isnull" and hasattr(model_field, "formfield"):
                form_field = model_field.formfield(
                    required=filter_field.extra.get("required", False)
                )

            if getattr(model_field, 'choices', None):
                if filter_type == 'exact':
                    form_field = ModelToFormChoiceField(model, filter_field.field_name)
                elif filter_type == 'in':
                    form_field = ModelToFormMultipleChoiceField(model, filter_field.field_name)

            if isinstance(model_field, (models.AutoField, models.OneToOneField, models.ForeignKey,
                                        models.ManyToManyField, models.ManyToOneRel, models.ManyToManyRel)):
                if filter_type == 'in':
                    form_field = GlobalIDMultipleChoiceField(required=False)

        # Fallback to field defined on filter if we can't get it from the
        # model field
        if not form_field:
            form_field = filter_field.field

        field_type = convert_form_field(form_field).Argument()
        field_type.description = filter_field.label
        args[name] = field_type

    return args


def get_filterset_class(filterset_class, **meta):
    """Get the class to be used as the FilterSet"""
    if filterset_class:
        # If were given a FilterSet class, then set it up and
        # return it
        return setup_filterset(filterset_class)
    return custom_filterset_factory(**meta)

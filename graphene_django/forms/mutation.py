# from django import forms
from collections import OrderedDict

import graphene
from graphene import Field, InputField
from graphene.relay.mutation import ClientIDMutation
from graphene.types.mutation import MutationOptions

from graphql_relay import from_global_id

from django import forms
from django.utils.datastructures import MultiValueDict
from django.forms.models import modelform_factory

# from graphene.types.inputobjecttype import (
#     InputObjectTypeOptions,
#     InputObjectType,
# )
from graphene.types.utils import yank_fields_from_attrs
from graphene_django.registry import get_global_registry

from ..types import ErrorType
from .converter import convert_form_field

import natsort


def fields_for_form(form, only_fields, exclude_fields, options={}):
    fields = OrderedDict()
    for name, field in form.fields.items():
        is_not_in_only = only_fields and name not in only_fields
        is_excluded = (
            name
            in exclude_fields  # or
            # name in already_created_fields
        )

        if is_not_in_only or is_excluded:
            continue

        fields[name] = convert_form_field(field, **options)
    return fields


class BaseDjangoFormMutation(ClientIDMutation):
    class Meta:
        abstract = True

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        form = cls.get_form(root, info, **input)

        if form.is_valid():
            return cls.perform_mutate(form, info)
        else:
            errors = ErrorType.from_errors(form.errors)
            return cls(errors=errors)

    @classmethod
    def get_form(cls, root, info, **input):
        form_kwargs = cls.get_form_kwargs(root, info, **input)
        return cls._meta.form_class(**form_kwargs)

    @classmethod
    def get_form_kwargs(cls, root, info, **input):
        if info and info.path:
            prefix = info.path[0]
            kwargs = {
                "prefix": prefix,
                "data": {'{}-{}'.format(prefix, key): value for key, value in input.items()},
            }
        else:
            kwargs = {
                "data": input
            }

        pk = input.pop("id", None)
        if pk:
            try:
                pk = from_global_id(pk)[1]
            except Exception:
                raise forms.ValidationError('invalid id format')
            instance = cls._meta.model._default_manager.get(pk=pk)
            kwargs["instance"] = instance

        if info and hasattr(info.context, 'FILES'):
            kwargs["files"] = info.context.FILES

        return kwargs


class DjangoFormMutationOptions(MutationOptions):
    form_class = None


class DjangoFormMutation(BaseDjangoFormMutation):
    class Meta:
        abstract = True

    errors = graphene.List(ErrorType)

    @classmethod
    def __init_subclass_with_meta__(
        cls, form_class=None, only_fields=(), exclude_fields=(), **options
    ):

        if not form_class:
            raise Exception("form_class is required for DjangoFormMutation")

        form = form_class()
        input_fields = fields_for_form(form, only_fields, exclude_fields)
        output_fields = fields_for_form(form, only_fields, exclude_fields)

        _meta = DjangoFormMutationOptions(cls)
        _meta.form_class = form_class
        _meta.fields = yank_fields_from_attrs(output_fields, _as=Field)

        input_fields = yank_fields_from_attrs(input_fields, _as=InputField)
        super(DjangoFormMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def perform_mutate(cls, form, info):
        form.save()
        return cls(errors=[], **form.cleaned_data)

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        form = cls.get_form(root, info, **input)

        if form.is_valid():
            return cls.perform_mutate(form, info)
        else:
            errors = ErrorType.from_errors(form.errors)
            if form.prefix:
                p = len(form.prefix) + 1
                return cls(errors=errors, **{
                    key[p:] : value
                    for key, value in form.data.items()})
            else:
                return cls(errors=errors, **form.data)



class DjangoModelMutationOptions(DjangoFormMutationOptions):
    model = None
    return_field_name = None


class DjangoCreateModelMutation(BaseDjangoFormMutation):
    inject_id = False
    fields_for_form_options = {}

    class Meta:
        abstract = True

    errors = graphene.List(ErrorType)

    @classmethod
    def __init_subclass_with_meta__(
            cls,
            form_class=None,
            model=None,
            return_field_name=None,
            only_fields=(),
            exclude_fields=(),
            fields=None, exclude=None,
            formfield_callback=None, widgets=None, localized_fields=None,
            labels=None, help_texts=None, error_messages=None,
            field_classes=None,
            disable_partial_update=None,
            **options
    ):
        _form_class = form_class
        _modelform_factory_options = dict(
            formfield_callback=formfield_callback, widgets=widgets, localized_fields=localized_fields,
            labels=labels, help_texts=help_texts, error_messages=error_messages,
            field_classes=field_classes)
        if not form_class:
            if model:
                form_class = modelform_factory(
                    model, fields=fields, exclude=exclude, **_modelform_factory_options)
            else:
                raise Exception("form_class is required for DjangoModelFormMutation")

        if not model:
            model = form_class._meta.model

        if not model:
            raise Exception("model is required for DjangoModelFormMutation")

        fields_for_form_options = dict(cls.fields_for_form_options.items())
        if disable_partial_update:
            fields_for_form_options['force_required_false'] = False

        form = form_class()
        input_fields = fields_for_form(form, only_fields, exclude_fields, fields_for_form_options)
        if cls.inject_id:
            input_fields["id"] = graphene.ID(required=True)

        registry = get_global_registry()
        model_type = registry.get_type_for_model(model)
        if not model_type:
            raise Exception("No type registered for model: {}".format(model.__name__))

        if not return_field_name:
            model_name = model.__name__
            return_field_name = model_name[:1].lower() + model_name[1:]

        output_fields = OrderedDict()

        output_fields[return_field_name] = graphene.Field(model_type)

        edge_type = model_type._meta.connection_field_class(model_type).type.Edge
        output_fields['edge'] = graphene.Field(edge_type)

        _meta = DjangoModelMutationOptions(cls)
        _meta.form_class = form_class
        _meta.model = model
        _meta.return_field_name = return_field_name
        _meta.fields = yank_fields_from_attrs(output_fields, _as=Field)
        _meta.edge_type = edge_type

        _meta._form_class = _form_class
        _meta._input_fields = input_fields
        _meta._modelform_factory_options = _modelform_factory_options
        _meta._disable_partial_update = disable_partial_update

        input_fields = yank_fields_from_attrs(input_fields, _as=InputField)
        super(DjangoCreateModelMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def perform_mutate(cls, form, info):
        obj = form.save()
        kwargs = {
            cls._meta.return_field_name: obj,
            'edge': cls._meta.edge_type(node=obj)
        }
        return cls(errors=[], **kwargs)


class DjangoUpdateModelMutation(DjangoCreateModelMutation):
    inject_id = True
    fields_for_form_options = {'force_required_false': True}

    class Meta:
        abstract = True

    @classmethod
    def get_form(cls, root, info, **input):
        form_kwargs = cls.get_form_kwargs(root, info, **input)
        if (not cls._meta._form_class) and (not cls._meta._disable_partial_update):
            fields = set(input.keys())
            fields.remove('id')

            if not fields.difference(set(cls._meta._input_fields.keys())):
                form_class = modelform_factory(
                    cls._meta.model, fields=tuple(fields), exclude=(), **cls._meta._modelform_factory_options)
                return form_class(**form_kwargs)
        return cls._meta.form_class(**form_kwargs)



class DjangoDeleteModelMutation(ClientIDMutation):
    class Meta:
        abstract = True

    errors = graphene.List(ErrorType)

    @classmethod
    def __init_subclass_with_meta__(
            cls,
            model=None,
            **options
    ):
        input_fields = OrderedDict()
        input_fields["id"] = graphene.Field(graphene.ID, required=True)

        output_fields = OrderedDict()
        output_fields['deleted_id'] = graphene.Field(graphene.ID)

        _meta = MutationOptions(cls)
        _meta.model = model
        _meta.fields = yank_fields_from_attrs(output_fields, _as=Field)

        print(input_fields)
        super(DjangoDeleteModelMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        _id = input['id']
        try:
            obj = cls._meta.model.objects.get(pk=from_global_id(_id)[1])
        except Exception:
            return cls(errors=[ErrorType(field='id', messages=['no id found'])])

        obj.delete()
        return cls(errors=[], deleted_id=_id)

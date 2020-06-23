# from django import forms
from collections import OrderedDict

import graphene
from graphene import Field, InputField
from graphene.relay.mutation import ClientIDMutation
from graphene.types.mutation import MutationOptions
from graphene.utils.str_converters import to_camel_case

from graphql_relay import from_global_id, to_global_id

from django import forms
from django.utils.datastructures import MultiValueDict
from django.forms.models import modelform_factory, ModelFormMetaclass

# from graphene.types.inputobjecttype import (
#     InputObjectTypeOptions,
#     InputObjectType,
# )
from graphene.types.utils import yank_fields_from_attrs
from graphene_django.registry import get_global_registry

from ..types import ErrorType
from .converter import convert_form_field, ModelToFormChoiceField

import natsort


class CustomModelFormMetaclassCallback(object):
    def __init__(self, model, s):
        self.model = model
        self.s = s

    def __call__(self, f, **kwargs):
        if f.name in self.s:
            return ModelToFormChoiceField(self.model, f.name, required=not f.null, **kwargs)
        return f.formfield(**kwargs)


class CustomModelFormMetaclass(ModelFormMetaclass):
    def __new__(mcs, name, bases, attrs):
        # print(mcs, name, bases, 'attrs=', attrs)
        # print('attrs.get Meta', attrs.get('Meta'))
        if 'Meta' in attrs:
            # print(attrs['Meta'].model)
            d = {}
            for field in attrs['Meta'].model._meta.get_fields():
                # print(field, field.name, type(field), getattr(field, 'choices', None))
                if getattr(field, 'choices', None):
                    # d[field.name] = lambda *args, **kwargs: ModelToFormChoiceField(attrs['Meta'].model, field.name)
                    # d[field.name] = attrs['Meta'].model, field.name # lambda *args, **kwargs: ModelToFormChoiceField(attrs['Meta'].model, field.name)
                    d[field.name] = ModelToFormChoiceField

            # attrs['Meta'].field_classes = d
            # attrs['formfield_callback'] = lambda f, **kwargs: ModelToFormChoiceField(attrs['Meta'].model, f.name, **kwargs) if f.name in d else f.formfield(**kwargs)
            attrs['formfield_callback'] = CustomModelFormMetaclassCallback(attrs['Meta'].model, d)

        return super().__new__(mcs, name, bases, attrs)


class GrapheneModelForm(forms.BaseModelForm, metaclass=CustomModelFormMetaclass):
    pass


def fields_for_form(form, only_fields, exclude_fields, options={}, is_model_field=False):
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
        # print(form, dir(form._meta))
        # print("convert", field, options)
        fields[name] = convert_form_field(field, **options)
    return fields


class BaseDjangoFormMutation(ClientIDMutation):
    class Meta:
        abstract = True

    @classmethod
    def __init_subclass_with_meta__(cls, *args, **kwargs):
        input_fields = kwargs.pop('input_fields', {})
        if 'form_prefix' in input_fields:
            raise Exception('_prefix is reserved by BaseDjangoFormMutation')
        input_fields['form_prefix'] = graphene.String()
        super(BaseDjangoFormMutation, cls).__init_subclass_with_meta__(*args, input_fields=input_fields, **kwargs)


    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        form = cls.get_form(root, info, **input)

        if form.is_valid():
            return cls.perform_mutate(form, info)
        else:
            errors = ErrorType.from_errors(form.errors)
            return cls(errors=errors)

    @classmethod
    def get_form_class(cls, root, info, **input):
        return cls._meta.form_class

    @classmethod
    def get_form(cls, root, info, **input):
        registry = get_global_registry()

        form_class = cls.get_form_class(root, info, **input)

        try:
            form_kwargs = cls.get_form_kwargs(root, info, **input)
        except Exception as e:
                form = form_class()
                form.cleaned_data = {}
                form.full_clean()
                form.add_error(None, e)
                return form

        for name, field in form_class.base_fields.items():
            try:
                name = '{}-{}'.format(form_kwargs['prefix'], name) if form_kwargs.get('prefix') else name
                if name not in form_kwargs['data']:
                    continue

                if isinstance(field, forms.ModelMultipleChoiceField):
                    model_type = registry.get_type_for_model(field.queryset.model)
                    for i, gid in enumerate(form_kwargs['data'][name]):
                        type_name, pk = from_global_id(gid)

                        if type_name == model_type._meta.name:
                            form_kwargs['data'][name][i] = pk
                elif isinstance(field, forms.ModelChoiceField):
                    model_type = registry.get_type_for_model(field.queryset.model)
                    type_name, pk = from_global_id(form_kwargs['data'][name])
                    if type_name == model_type._meta.name:
                        form_kwargs['data'][name] = pk
            except Exception:
                continue

        if 'files' in form_kwargs:
            for name, field in form_class.base_fields.items():
                key = '{}-{}'.format(form_kwargs['prefix'], to_camel_case(name)) if form_kwargs.get('prefix') else to_camel_case(name)
                if key in form_kwargs['files'] and name != key:
                    try:
                        form_kwargs['files'].setlist(name, form_kwargs['files'].getlist(key))
                    except AttributeError:
                        form_kwargs['files'][name] = form_kwargs['files'][key]

        return form_class(**form_kwargs)


    @classmethod
    def get_form_kwargs(cls, root, info, **input):
        prefix = input.pop('form_prefix', None)

        kwargs = {
            "data": input,
        }
        if info and hasattr(info.context, 'FILES'):
            if prefix:
                kwargs["files"] = MultiValueDict()
                for key in info.context.FILES.keys():
                    if not key.startswith('{}-'.format(prefix)):
                        continue
                    real_key = key[len(prefix) + 1:]

                    try:
                        kwargs["files"].setlist(real_key, info.context.FILES.getlist(key))
                    except AttributeError:
                        kwargs["files"][real_key] = info.context.FILES.get(key)

            else:
                kwargs["files"] = info.context.FILES

        pk = input.pop("id", None)
        if pk:
            try:
                pk = from_global_id(pk)[1]
            # except Exception:
            #     raise forms.ValidationError('invalid id format')
            # try:
                instance = cls._meta.model._default_manager.get(pk=pk)
            except cls._meta.model.DoesNotExist:
                raise forms.ValidationError(forms.ModelChoiceField.default_error_messages['invalid_choice'], code='invalid_choice')
            kwargs["instance"] = instance

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
        _meta.only_fields = only_fields
        _meta.exclude_fields = exclude_fields

        input_fields = yank_fields_from_attrs(input_fields, _as=InputField)
        super(DjangoFormMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def perform_mutate(cls, form, info):
        form.save()
        return cls(errors=[], **{
            key: value
            for key, value in form.cleaned_data.items()
            if cls._check_form_key(key)})

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
                    for key, value in form.data.items()
                    if cls._check_form_key(key)})
            else:
                return cls(errors=errors, **{
                    key: value
                    for key, value in form.data.items()
                    if cls._check_form_key(key)})

    @classmethod
    def _check_form_key(cls, key):
        if cls._meta.only_fields:
            return key in cls._meta.only_fields
        elif cls._meta.exclude_fields:
            return key not in cls._meta.exclude_fields
        return True



class DjangoModelMutationOptions(DjangoFormMutationOptions):
    model = None
    return_field_name = None


class DjangoCreateModelMutation(BaseDjangoFormMutation):
    inject_id = False
    inject_id_required = True
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
            form=GrapheneModelForm,
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
        input_fields = fields_for_form(form, only_fields, exclude_fields, fields_for_form_options, is_model_field=True)
        if cls.inject_id:
            input_fields["id"] = graphene.ID(required=cls.inject_id_required)

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
        _meta.connection_field_class = model_type._meta.connection_field_class(model_type)
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
    def create_result(cls, form, info, obj):
        kwargs = {
            cls._meta.return_field_name: obj,
            'edge': cls._meta.edge_type(
                cursor=cls._meta.connection_field_class.instance_to_cursor(obj),
                node=obj,
            )
        }
        return cls(errors=[], **kwargs)

    @classmethod
    def perform_mutate(cls, form, info):
        obj = form.save()
        return cls.create_result(form, info, obj)


class DjangoGetOrCreateModelMutation(DjangoCreateModelMutation):
    class Meta:
        abstract = True

    @classmethod
    def mutate_and_get_payload(cls, root, info, **input):
        form = cls.get_form(root, info, **input)

        if form.is_valid():
            try:
                obj = cls._meta.model.objects.get(**form.data)
                return cls.create_result(form, info, obj)
            except cls._meta.model.DoesNotExist:
                pass

            return cls.perform_mutate(form, info)
        else:
            errors = ErrorType.from_errors(form.errors)
            return cls(errors=errors)


class DjangoUpdateModelMutation(DjangoCreateModelMutation):
    inject_id = True
    fields_for_form_options = {'force_required_false': True}

    class Meta:
        abstract = True

    @classmethod
    def get_form_class(cls, root, info, **input):
        if (not cls._meta._form_class) and (not cls._meta._disable_partial_update):
            fields = set(input.keys())
            fields.remove('id')

            if not fields.difference(set(cls._meta._input_fields.keys())):
                form_class = modelform_factory(
                    cls._meta.model, fields=tuple(fields), exclude=(), **cls._meta._modelform_factory_options)
                return form_class
        return cls._meta.form_class


class DjangoUpdateOrCreateModelMutation(DjangoCreateModelMutation):
    inject_id = True
    inject_id_required = False

    class Meta:
        abstract = True



class DjangoDeleteModelMutation(BaseDjangoFormMutation):
    class Meta:
        abstract = True

    errors = graphene.List(ErrorType)

    @classmethod
    def __init_subclass_with_meta__(
            cls,
            model=None,
            form_class=None,
            only_fields=(), exclude_fields=(),
            add_id=True,
            **options
    ):
        org_form_class = form_class
        if form_class:
            form = form_class()
            input_fields = fields_for_form(form, only_fields, exclude_fields)
            if not model:
                model = form_class._meta.model
            if add_id:
                input_fields["id"] = graphene.Field(graphene.ID, required=True)
        else:
            form_class = modelform_factory(model, fields=(), exclude=())
            input_fields = OrderedDict()
            input_fields["id"] = graphene.Field(graphene.ID, required=True)

        output_fields = OrderedDict()
        output_fields['deleted_id'] = graphene.Field(graphene.ID)

        _meta = MutationOptions(cls)
        _meta.model = model
        _meta.form_class = form_class
        _meta.org_form_class = org_form_class
        _meta.fields = yank_fields_from_attrs(output_fields, _as=Field)
        _meta.only_fields = only_fields
        _meta.exclude_fields = exclude_fields

        super(DjangoDeleteModelMutation, cls).__init_subclass_with_meta__(
            _meta=_meta, input_fields=input_fields, **options
        )

    @classmethod
    def perform_mutate(cls, form, info):
        registry = get_global_registry()
        model_type = registry.get_type_for_model(cls._meta.model)

        gid = to_global_id(model_type.__name__, form.instance.pk)
        obj = form.save()

        if not cls._meta.org_form_class:
            obj.delete()

        return cls(errors=[], deleted_id=gid)

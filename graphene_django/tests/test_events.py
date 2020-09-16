import json
import pytest
from unittest import mock
from asgiref.sync import async_to_sync, sync_to_async

from channels import DEFAULT_CHANNEL_LAYER
from channels.layers import get_channel_layer
from django.db.models.signals import post_save

from .. import events

from . import models


@pytest.fixture(scope='function', autouse=True)
def clear_post_save():
    events._mem = []  # これがないとupdatedでフリーズする
    yield



def test_sync_event_send():
    group = 'sync-subsc'
    channel_layer = get_channel_layer(DEFAULT_CHANNEL_LAYER)
    channel = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(group, channel)

    event = events.SubscriptionEvent('operation', {'field': 'value'})
    event.send(group)

    message = async_to_sync(channel_layer.receive)(channel)
    assert isinstance(message, dict)
    assert message['operation'] == 'operation'
    assert message['instance'] == {'field': 'value'}
    assert message['__class__'] == ('graphene_django.events', 'SubscriptionEvent')

    instance = events.SubscriptionEvent.from_dict(message)
    assert instance.operation == 'operation'
    assert instance.instance == {'field': 'value'}


@pytest.mark.asyncio
async def test_async_event_send():
    group = 'async-subsc'
    channel_layer = get_channel_layer(DEFAULT_CHANNEL_LAYER)
    channel = await channel_layer.new_channel()
    await channel_layer.group_add(group, channel)

    event = events.SubscriptionEvent('operation', {'field': 'value'})
    event.send(group)

    message = await channel_layer.receive(channel)
    assert isinstance(message, dict)
    assert message['operation'] == 'operation'
    assert message['instance'] == {'field': 'value'}
    assert message['__class__'] == ('graphene_django.events', 'SubscriptionEvent')

    recovered_event = events.SubscriptionEvent.from_dict(message)
    assert recovered_event.operation == 'operation'
    assert recovered_event.instance == {'field': 'value'}


@pytest.mark.django_db
def test_post_save_created():
    group = 'pet-created'
    post_save.connect(events.post_save_subscription(group), sender=models.Pet,
                      dispatch_uid="remainder_pet_post_save")
    
    channel_layer = get_channel_layer(DEFAULT_CHANNEL_LAYER)
    channel = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(group, channel)

    with mock.patch('django.db.transaction.get_autocommit', return_value=True):
        models.Pet.objects.create(name="ichi", age=10)

    message = async_to_sync(channel_layer.receive)(channel)
    assert isinstance(message, dict)
    assert message['operation'] == 'post_save'
    assert message['__class__'] == ('graphene_django.events', 'ModelCreatedSubscriptionEvent')

    recovered_event = events.SubscriptionEvent.from_dict(message)
    assert isinstance(recovered_event, events.ModelCreatedSubscriptionEvent)
    assert recovered_event.operation == 'post_save'
    assert isinstance(recovered_event.instance, models.Pet)
    assert recovered_event.instance.name == 'ichi'
    assert recovered_event.instance.age == 10

    models.Pet.objects.all().delete()


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_post_save_updated():
    pet = await sync_to_async(models.Pet.objects.create)(name="ichi", age=10)

    group = 'pet-updated'
    post_save.connect(events.post_save_subscription(group), sender=models.Pet,
                      dispatch_uid="remainder_pet_post_save")
    
    channel_layer = get_channel_layer(DEFAULT_CHANNEL_LAYER)
    channel = await channel_layer.new_channel()
    await channel_layer.group_add(group, channel)

    pet.age = 11
    with mock.patch('django.db.transaction.get_autocommit', return_value=True):
        await sync_to_async(pet.save)()

    message = await channel_layer.receive(channel)
    assert isinstance(message, dict)
    assert message['operation'] == 'post_save'
    assert message['__class__'] == ('graphene_django.events', 'ModelUpdatedSubscriptionEvent')

    recovered_event = events.SubscriptionEvent.from_dict(message)
    assert isinstance(recovered_event, events.ModelUpdatedSubscriptionEvent)
    assert recovered_event.operation == 'post_save'
    assert isinstance(recovered_event.instance, models.Pet)
    assert recovered_event.instance.name == 'ichi'
    assert recovered_event.instance.age == 11

    await sync_to_async(models.Pet.objects.all().delete)()

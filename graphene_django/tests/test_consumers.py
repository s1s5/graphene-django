import json
import pytest
import functools
import asyncio

import graphene

from asgiref.sync import async_to_sync
from channels import DEFAULT_CHANNEL_LAYER
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator


from .. import consumers

class AsyncConsumerTest(consumers.AsyncConsumer):
    def stop(self, message):
        raise consumers.StopConsumer()


def test_async_consumer():
    consumer = AsyncConsumerTest({})
    
    channel_layer = get_channel_layer(DEFAULT_CHANNEL_LAYER)

    receive = async_to_sync(channel_layer.new_channel)()
    send = async_to_sync(channel_layer.new_channel)()

    async_to_sync(channel_layer.send)(receive, {'type': 'stop'})

    loop = asyncio.get_event_loop()
    loop.run_until_complete(consumer(
        functools.partial(
            channel_layer.receive, receive
        ),
        functools.partial(
            channel_layer.send, send
        ),
    ))
    loop.close()


@pytest.fixture()
async def communicator():
    class Query(graphene.ObjectType):
        hello = graphene.String()

        def resolve_hello(root, context):
            return 'hello world'

    class Subscription(graphene.ObjectType):
        hello = graphene.String()
        count = graphene.Int(up_to=graphene.Int())

        def resolve_hello(root, context):
            def f(event):
                return event['message']
            return consumers.ChannelGroupObservable("hello-group").map(f)

        def resolve_count(root, context, up_to):
            class AsyncIterable(object):
                def __init__(self, up_to):
                    self.up_to = up_to
                    self.counter = -1

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    self.counter += 1
                    if self.counter < self.up_to:
                        return self.counter
                    else:
                        raise StopAsyncIteration
            return AsyncIterable(up_to)

    schema = graphene.Schema(query=Query, subscription=Subscription)
    app = functools.partial(consumers.AsyncWebsocketConsumer, schema=schema)
    communicator = WebsocketCommunicator(app, "/")
    connected, subprotocol = await communicator.connect()
    assert connected
    assert subprotocol == 'graphql-ws'

    await communicator.send_to(text_data=json.dumps({
        "type": "connection_init",
    }))

    yield communicator

    await communicator.send_to(text_data=json.dumps({
        "type": "stop",
    }))

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_hello_world(communicator):
    await communicator.send_to(text_data=json.dumps({
        "type": "start",
        "payload": {
            "query": "query { hello }"
        }
    }))

    raw_response = await communicator.receive_from()
    response = json.loads(raw_response)
    assert response['type'] == 'data'
    assert response['payload']['data'] == {'hello': 'hello world'}


@pytest.mark.asyncio
async def test_observable(communicator):
    _id = 1
    await communicator.send_to(text_data=json.dumps({
        "type": "start",
        "id": _id,
        "payload": {
            "query": "subscription { hello }"
        }
    }))

    await asyncio.sleep(0.001) # これが重要。サーバー側に処理を返してあげないとgroup_addが遅れて失敗する

    channel_layer = get_channel_layer(DEFAULT_CHANNEL_LAYER)
    await channel_layer.group_send("hello-group", {"message": "hello-subsc"})
    
    raw_response = await communicator.receive_from()
    response = json.loads(raw_response)

    assert response['type'] == 'data'
    assert response['payload']['data'] == {'hello': 'hello-subsc'}

    await communicator.send_to(text_data=json.dumps({
        "type": "stop",
        "id": _id,
    }))

    # TODO: これ以降メッセージを受診しないことの確認はどうすればいいんだ


@pytest.mark.asyncio
async def test_async_iterable(communicator):
    _id = 1
    await communicator.send_to(text_data=json.dumps({
        "type": "start",
        "id": _id,
        "payload": {
            "query": "subscription { count(upTo: 3) }"
        }
    }))

    await asyncio.sleep(0.001) # これが重要。サーバー側に処理を返してあげないとgroup_addが遅れて失敗する

    for i in range(3):
        raw_response = await communicator.receive_from()
        response = json.loads(raw_response)
        assert response['type'] == 'data'
        assert response['payload']['data'] == {'count': i}

    raw_response = await communicator.receive_from()
    response = json.loads(raw_response)
    assert response['type'] == 'complete'

    await communicator.send_to(text_data=json.dumps({
        "type": "stop",
        "id": _id,
    }))

    # TODO: これ以降メッセージを受診しないことの確認はどうすればいいんだ

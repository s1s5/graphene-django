import functools
import asyncio

from asgiref.sync import async_to_sync
from channels import DEFAULT_CHANNEL_LAYER
from channels.layers import get_channel_layer

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

    print(receive, send)

    

import asyncio
import functools
import logging
import json
import uuid
from concurrent import futures as concurrent_futures

import six

from asgiref.sync import async_to_sync
from asyncio import ensure_future
from asyncio import get_event_loop
from channels import DEFAULT_CHANNEL_LAYER
from channels.db import database_sync_to_async
from channels.consumer import await_many_dispatch, get_handler_name, SyncConsumer, StopConsumer
from channels.layers import get_channel_layer
from rx.core import ObserverBase, ObservableBase
from rx.subjects import Subject
from graphql.execution.executors.sync import SyncExecutor
from graphql.execution.executors.asyncio import AsyncioExecutor
from graphql.execution.executors.asyncio_utils import asyncgen_to_observable
from graphene_django.settings import graphene_settings

from .events import SubscriptionEvent

logger = logging.getLogger(__name__)


class AttrDict:
    def __init__(self, data):
        self.__dict__ = data


class AsyncConsumer:
    def __init__(self, scope):
        self.scope = scope

    async def __call__(self, receive, send):
        self.base_send = send
        try:
            await await_many_dispatch([receive], self.dispatch)
        except StopConsumer:
            pass

    async def dispatch(self, message):
        handler = getattr(self, get_handler_name(message), None)
        if handler:
            await handler(message)
        else:
            raise ValueError("No handler for message type %s" % message["type"])

    async def send(self, message):
        await self.base_send(message)



class AsyncWebsocketConsumer(AsyncConsumer):
    _sync = False

    class CustomSyncExecutor(SyncExecutor):
        def __init__(self, loop):
            self.loop = loop

        def execute(self, fn, *args, **kwargs):
            result = super().execute(fn, *args, **kwargs)
            if hasattr(result, "__aiter__"):
                return asyncgen_to_observable(result, loop=self.loop)
            return result

    class CustomAsyncioExecutor(AsyncioExecutor):
        def execute(self, fn, *args, **kwargs):
            result = super().execute(fn, *args, **kwargs)
            if hasattr(result, "__aiter__"):
                return asyncgen_to_observable(result, loop=self.loop)
            return result

    class Observer(ObserverBase):
        def __init__(self, _send, _id):
            super().__init__()

            self._send = _send
            self._id = _id

        def _on_next_core(self, value):
            try:
                logger.debug("_on_next_core %s", value)
                if value.errors:
                    for error in value.errors:
                        logger.error('subscription error',
                                     exc_info=(type(error), error,
                                               error.__traceback__))
                self._send(self._id, 'data', dict(
                    data=value.data,
                    errors=[
                        {'name': str(type(x)), 'message': str(x)}
                        for x in value.errors] if value.errors else None,
                ))
            except Exception as e:
                logger.exception(e)

        def _on_error_core(self, error):
            logger.debug('_on_error_core %s', error)
            self._send(self._id, 'error', [{'name': str(type(error)), 'message': str(error)}])

        def _on_completed_core(self):
            logger.debug('_on_completed_core %s')
            self._send(self._id, 'complete', None)

    def __init__(self, *args, **kwargs):
        self.schema = kwargs.pop('schema', graphene_settings.SCHEMA)
        super().__init__(*args, **kwargs)
        self.disposable_map = {}

    async def websocket_connect(self, message):
        logger.debug('websocket_connect')
        await super().send({"type": "websocket.accept", "subprotocol": 'graphql-ws'})
        await super().send({
            'type': 'websocket.send',
            'text': json.dumps({
                "type": "connection_ack",
                "payload": uuid.uuid4().hex,
            }),
        })

    @database_sync_to_async
    def execute_schema_sync(self, request, loop):
        payload = request["payload"]
        context = AttrDict(self.scope)

        return self.schema.execute(
            payload["query"],
            operation_name=payload.get("operationName"),
            variable_values=payload.get("variables"),
            context_value=context,
            root_value=None,
            allow_subscriptions=True,

            executor=AsyncWebsocketConsumer.CustomSyncExecutor(loop=loop),
        )

    def execute_schema_async(self, request):
        payload = request["payload"]
        context = AttrDict(self.scope)

        return self.schema.execute(
            payload["query"],
            operation_name=payload.get("operationName"),
            variable_values=payload.get("variables"),
            context_value=context,
            root_value=None,
            allow_subscriptions=True,

            executor=AsyncWebsocketConsumer.CustomAsyncioExecutor(),
        )

    async def websocket_receive(self, message):
        logger.debug('websocket_receive %s', message)
        request = json.loads(message["text"])
        _id = request.get("id")

        if request["type"] == "connection_init":
            return

        elif request["type"] == "start":
            if self._sync:
                result = await self.execute_schema_sync(request, get_event_loop())
            else:
                result = self.execute_schema_async(request)

            logger.debug('result %s, %s', result, hasattr(result, "subscribe"))
            if hasattr(result, "subscribe"):
                observer = AsyncWebsocketConsumer.Observer(self._send, _id)
                disposable = result.subscribe(observer)
                self.disposable_map[_id] = disposable
            else:
                self._send(_id, 'data', dict(
                    data=result.data,
                    errors=[six.text_type(x) for x in result.errors] if result.errors else None,
                    extensions=result.extensions))

        elif request["type"] == "stop":
            disposable = self.disposable_map.get(_id, None)
            if disposable:
                disposable.dispose()

    def _send(self, _id, type, payload):
        logger.debug('sending %s, %s', type, payload)
        try:
            data = {
                "type": "websocket.send",
                "text": json.dumps(
                    {
                        "id": _id,
                        "type": type,
                        "payload": payload,
                    }
                ),
            }

            if asyncio._get_running_loop():
                ensure_future(super().send(data))
            else:
                async_to_sync(super().send)(data)

        except Exception as e:
            logger.exception(e)

    async def websocket_disconnect(self, message):
        logger.debug('websocket_disconnect')
        await super().send({"type": "websocket.close", "code": 1000})
        try:
            for disposable in self.disposable_map.values():
                try:
                    disposable.dispose()
                except Exception as e:
                    logger.exception(e)
            self.disposable_map = {}
        except Exception as e:
            logger.exception(e)
        finally:
            raise StopConsumer()


class SyncWebsocketConsumer(AsyncWebsocketConsumer):
    _sync = True


class ChannelGroupObservable(ObservableBase):
    def __init__(self, channel_group, channel_layer_alias=DEFAULT_CHANNEL_LAYER, loop=None, sync_mode=True, *args, **kwargs):
        self.channel_group = channel_group
        self.channel_layer_alias = channel_layer_alias
        self.loop = loop
        super().__init__(*args, **kwargs)
        self.sync_mode = sync_mode

    async def dispatch(self, observer):
        channel_layer = get_channel_layer(self.channel_layer_alias)
        channel_name = await channel_layer.new_channel()
        channel_receive = functools.partial(channel_layer.receive, channel_name)

        logger.debug('channel_layer.group_add(%s, %s)', self.channel_group, channel_name)
        await channel_layer.group_add(self.channel_group, channel_name)

        if self.sync_mode:
            dispatch = self._event_dispatch_sync
        else:
            dispatch = self._event_dispatch_async

        try:
            while True:
                await dispatch(observer, await channel_receive())

        except (StopConsumer, concurrent_futures.CancelledError):
            pass
        except Exception as e:
            observer.on_error(e)
        finally:
            await channel_layer.group_discard(self.channel_group, channel_name)
            logger.debug('channel_layer.group_discard(%s, %s)', self.channel_group, channel_name)

    @database_sync_to_async
    def _event_dispatch_sync(self, observer, event):
        observer.on_next(event)

    async def _event_dispatch_async(self, observer, event):
        observer.on_next(event)

    def _subscribe_core(self, observer):
        task = ensure_future(self.dispatch(observer))

        def dispose():
            async def await_task():
                await task

            task.cancel()
            ensure_future(await_task(), loop=self.loop)

        return dispose


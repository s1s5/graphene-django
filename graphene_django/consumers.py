import logging
import json

from asyncio import ensure_future
from channels.consumer import await_many_dispatch, get_handler_name, StopConsumer
from rx.core import ObserverBase
from graphql.execution.executors.asyncio import AsyncioExecutor
from graphql.execution.executors.asyncio_utils import asyncgen_to_observable
from graphene_django.settings import graphene_settings

logger = logging.getLogger(__name__)


class AttrDict:
    def __init__(self, data):
        self.data = data or {}

    def __getattr__(self, item):
        return self.get(item)

    def get(self, item):
        return self.data.get(item)


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
    class Executor(AsyncioExecutor):
        def execute(self, fn, *args, **kwargs):
            result = super().execute(fn, *args, **kwargs)
            if hasattr(result, '__aiter__'):
                return asyncgen_to_observable(result, loop=self.loop)
            return result

    class Observer(ObserverBase):
        def __init__(self, _send, _id):
            super().__init__()

            self._send = _send
            self._id = _id

        def _on_next_core(self, value):
            try:
                logger.debug('_on_next_core %s', value)
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
        super().__init__(*args, **kwargs)
        self.disposable_list = []

    async def websocket_connect(self, message):
        logger.debug('websocket_connect')
        await super().send({"type": "websocket.accept", "subprotocol": 'graphql-ws'})

    async def websocket_receive(self, message):
        logger.debug('websocket_receive %s', message)
        request = json.loads(message["text"])
        _id = request.get("id")

        if request["type"] == "connection_init":
            return

        elif request["type"] == "start":
            payload = request["payload"]
            context = AttrDict(self.scope)

            schema = graphene_settings.SCHEMA

            result = schema.execute(
                payload["query"],
                operation_name=payload.get("operationName"),
                variables=payload.get("variables"),
                context=context,
                root=None,
                allow_subscriptions=True,

                executor=AsyncWebsocketConsumer.Executor(),
            )

            if hasattr(result, "subscribe"):
                observer = AsyncWebsocketConsumer.Observer(self._send, _id)
                disposable = result.subscribe(observer)
                self.disposable_list.append(disposable)
            else:
                # self._send_result(_id, result)
                self._send(_id, 'data', result)

        elif request["type"] == "stop":
            pass

    def _send(self, _id, type, payload):
        logger.debug('sending %s, %s', type, payload)
        try:
            ensure_future(super().send({
                "type": "websocket.send",
                "text": json.dumps(
                    {
                        "id": _id,
                        "type": type,
                        "payload": payload,
                    }
                ),
            }))
        except Exception as e:
            logger.exception(e)

    async def websocket_disconnect(self, message):
        logger.debug('websocket_disconnect')
        await super().send({"type": "websocket.close", "code": 1000})
        try:
            for disposable in self.disposable_list:
                try:
                    disposable.dispose()
                except Exception as e:
                    logger.exception(e)
            self.disposable_list = []
        except Exception as e:
            logger.exception(e)
        finally:
            raise StopConsumer()

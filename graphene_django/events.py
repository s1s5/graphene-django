import importlib
import asyncio
from django.db import models
from django.core.serializers import serialize, deserialize
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


class SubscriptionEvent:
    def __init__(self, operation=None, instance=None):
        self.operation = operation
        self.instance = instance

    def send(self, channel_group):
        if callable(channel_group):
            group = channel_group(self)
        else:
            group = channel_group

        channel_layer = get_channel_layer()
        event = self.to_dict()

        if asyncio._get_running_loop():
            asyncio.run(channel_layer.group_send(group, event))
        else:
            async_to_sync(channel_layer.group_send)(group, event)

    def to_dict(self):
        return {
            "operation": self.operation,
            "instance": self.instance,
            "__class__": (self.__module__, self.__class__.__name__),
        }

    @staticmethod
    def from_dict(_dict):
        module_name, class_name = _dict.get("__class__")
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)

        return cls(operation=_dict.get("operation"), instance=_dict.get("instance"))


class ModelSubscriptionEvent(SubscriptionEvent):
    def __init__(self, operation=None, instance=None):
        super(ModelSubscriptionEvent, self).__init__(operation, instance)

        if type(self.instance) == str:
            # deserialize django object
            self.instance = list(deserialize("json", self.instance))[0].object

        if not isinstance(self.instance, models.Model):
            raise ValueError(
                "ModelSubscriptionEvent instance value must be a Django model"
            )

    def to_dict(self):
        _dict = super(ModelSubscriptionEvent, self).to_dict()

        _dict["instance"] = serialize("json", [self.instance])

        return _dict


class ModelCreatedSubscriptionEvent(ModelSubscriptionEvent):
    created = True


class ModelUpdatedSubscriptionEvent(ModelSubscriptionEvent):
    created = False


_mem = []


def post_save_subscription(channel_group):

    def f(sender, instance, created, **kwargs):
        if created:
            event = ModelCreatedSubscriptionEvent('post_save', instance)
        else:
            event = ModelUpdatedSubscriptionEvent('post_save', instance)
        event.send(channel_group)

    _mem.append(f)
    return f

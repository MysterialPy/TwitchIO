"""
The MIT License (MIT)

Copyright (c) 2017-2020 TwitchIO

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""

import asyncio
import enum
import logging

import sanic
from sanic import request
from sanic import response

from twitchio.ext.webhooks.utils import Topic, StreamChangedNotification, UserChangedNotification, \
    UserFollowsNotification

log = logging.getLogger(__name__)


NOTIFICATION_TYPE_BY_TOPIC = {
    Topic.stream_changed: StreamChangedNotification,
    Topic.user_changed: UserChangedNotification,
    Topic.user_follows: UserFollowsNotification
}


class WebhookEventDispatcher:

    __instances = set()
    __dispatcher = None

    def __init__(self, loop: asyncio.AbstractEventLoop = None):
        self.__instances.add(self)
        self.loop = loop or asyncio.get_event_loop()

    def __init_subclass__(cls, **kwargs):
        cls._registered_dispatcher(cls)

    @classmethod
    def _registered_dispatcher(cls, new_cls=None):
        if new_cls:
            WebhookEventDispatcher.__dispatcher = new_cls
        return WebhookEventDispatcher.__dispatcher

    @staticmethod
    def accept_subscription(request: request.Request, topic: enum.Enum):
        """Handle Twitch challenge requests.

        Accept Twitch subscriptions by responding the request with the provided challenge string.

        Parameters
        ----------
        request: sanic.request.Request
            The challenge request received from Twitch
        topic: enum.Enum
            The topic being subscribed to

        Returns
        -------

        response.HTTPResponse
            status code: 200 if the request has correctly been processed
            status code: 400 otherwise
        """
        try:
            mode = request.args['hub.mode'][0]

            if mode == 'subscribe' or mode == 'unsubscribe':
                return response.HTTPResponse(body=request.args['hub.challenge'][0], status=200)

            elif mode == 'denied':
                reason = request.args.get('hub.reason', 'no reason')
                log.warning(f'{topic.name} webhook subscribe request denied ({request.args}) , reason: {reason}.')

            return response.HTTPResponse(status=200)

        except KeyError:
            return response.HTTPResponse(status=400)

    @classmethod
    async def bulk_process_notification(cls, request: request.Request, topic: enum.Enum):
        """Process the received notification.

        - Check if the related topic is supported.
        - Pass the notification info to the dispatchers.

        Parameters
        ----------
        request: sanic.request.Request
            The challenge request received from Twitch
        topic: enum.Enum
            Topic whose notification is being processed

        Returns
        -------

        response.HTTPResponse
            status code: 202 if the request has correctly been processed
            status code: 400 otherwise
        """
        if topic not in NOTIFICATION_TYPE_BY_TOPIC:
            log.error(f'Invalid topic "{topic.name}", the notification has been ignored')
            return

        try:
            params = {param: request.args.get(param) for param in NOTIFICATION_TYPE_BY_TOPIC[topic].valid_params}
            data = request.json['data'][0] if request.json['data'] else {}

            for instance in cls.__instances:
                await instance.process_notification(data, topic, params)

            return response.HTTPResponse(status=202)

        except KeyError:
            return response.HTTPResponse(status=400)

    async def process_notification(self, data: dict, topic: enum.Enum, params: dict):
        """Filter the notification and call the related callback.

        Parameters
        ----------
        data: dict
            Notification content
        topic: enum.Enum
            Topic whose notification is being processed
        params: dict
            Topic parameters
        """
        try:
            cls = NOTIFICATION_TYPE_BY_TOPIC[topic]
            notification = cls(**data)
            if cls == StreamChangedNotification:
                if data:
                    await self.event_stream_updated(params, notification)
                else:
                    await self.event_stream_offline(params, notification)
            elif cls == UserChangedNotification:
                await self.event_user_updated(params, notification)
            elif cls == UserFollowsNotification:
                if not params['from_id']:
                    await self.event_following_user(params, notification)
                else:
                    await self.event_followed_by_user(params, notification)

        except Exception as error:
            await self.webhook_notification_error(topic, data, params, error)

    async def webhook_notification_error(self, topic: enum.Enum, data: dict, params: dict, error: Exception):
        """Handle the error raised during the notification processing

        Parameters
        ----------
        topic: enum.Enum
            Topic whose notification is being processed
        data: dict
            Notification content
        params: dict
            Topic parameters
        error: Exception
            The error being raised
        """
        log.error(f"Exception '{type(error).__name__}' raised for topic  '{topic.name}' (params={params})",
                  exc_info=(type(error), error, error.__traceback__))

    async def event_stream_updated(self, params: dict, notification: StreamChangedNotification):
        """Callback called when a user starts or updates a stream.

        Parameters
        ----------
        params: dict
            Topic parameters
        notification: StreamChangedNotification
            Topic data object
        """

    async def event_stream_offline(self, params: dict, notification: StreamChangedNotification):
        """Callback called when a user stops a stream.

        Parameters
        ----------
        params: dict
            Topic parameters
        notification: StreamChangedNotification
            Topic data object
        """

    async def event_user_updated(self, params: dict, notification: UserChangedNotification):
        """Callback called when a user's data is updated.

        Parameters
        ----------
        params: dict
            Topic parameters
        notification: UserChangedNotification
            Topic data object
        """

    async def event_following_user(self, params: dict, notification: UserFollowsNotification):
        """Callback called when a user is being followed by someone

        Parameters
        ----------
        params: dict
            Topic parameters
        notification: UserFollowsNotification
            Topic data object
        """

    async def event_followed_by_user(self, params: dict, notification: UserFollowsNotification):
        """Callback called when a user is following someone

        Parameters
        ----------
        params: dict
            Topic parameters
        notification: UserFollowsNotification
            Topic data object
        """

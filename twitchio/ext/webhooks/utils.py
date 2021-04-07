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

import collections
import enum
import hashlib
import hmac
import logging

from sanic import response, blueprints, request

log = logging.getLogger(__name__)


recent_notification_ids = collections.deque(maxlen=100)


class Topic(enum.Enum):

    stream_changed = 'StreamChanged'
    user_changed = 'UserChanged'
    user_follows = 'UserFollows'


class Notification:
    """Twitch webhook notification dataclass."""

    __slots__ = ()
    valid_params = ()

    def __init__(self, **params):
        for slot in self.__slots__:
            setattr(self, slot, params.get(slot))

    def __repr__(self):
        formatted_params = [f"{param}={getattr(self, param)}" for param in self.__slots__]
        return f"<{self.__class__.__name__} {', '.join(formatted_params)}>"


class StreamChangedNotification(Notification):
    """Twitch 'StreamChanged' webhook notification dataclass."""

    __slots__ = ('game_id', 'id', 'language', 'started_at', 'tag_ids', 'thumbnail_url', 'title', 'type', 'user_id',
                 'user_name', 'viewer_count')
    valid_params = ('user_id',)


class UserChangedNotification(Notification):
    """Twitch 'UserChanged' webhook notification dataclass."""

    __slots__ = ('id', 'login', 'display_name', 'type', 'broadcaster_type', 'description', 'profile_image_url',
                 'offline_image_url', 'view_count')
    valid_params = ('id',)


class UserFollowsNotification(Notification):
    """Twitch 'UserFollows' webhook notification dataclass."""

    __slots__ = ("from_id", "from_name", "to_id", "to_name", "followed_at")
    valid_params = ('from_id', 'to_id')


def verify_payload(route: blueprints.FutureRoute):
    """
    Decorator which verifies that a request was been sent from Twitch by comparing the 'X-Hub-Signature'
    header.
    """
    async def inner(request: request.Request, *args, **kwargs):

        secret = getattr(request.app.config, 'TWITCH_WEBHOOK_SECRET', None)

        if secret:

            secret = secret.encode('utf-8')
            digest = hmac.new(secret, msg=request.body, digestmod=hashlib.sha256).hexdigest()

            if not hmac.compare_digest(digest, request.headers.get('X-Hub-Signature', '')[7:]):
                log.warning("The hash for this notification is invalid")
                return response.HTTPResponse(status=403)

        return await route(request, *args, **kwargs)

    return inner


def remove_duplicates(route: blueprints.FutureRoute):
    """Decorator which prevents duplicate notifications being processed more than once."""

    async def inner(request: request.Request, *args, **kwargs):
        notification_id = request.headers.get('Twitch-Notification-ID')

        if notification_id in recent_notification_ids:
            log.warning(f'Received duplicate notification with ID {notification_id}, discarding.')

            return response.HTTPResponse(status=200)

        recent_notification_ids.append(notification_id)
        return await route(request, *args, **kwargs)

    return inner

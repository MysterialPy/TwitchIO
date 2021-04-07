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

import logging

import sanic
from sanic import request

from twitchio.ext.webhooks.utils import remove_duplicates, verify_payload, Topic
from twitchio.ext.webhooks.dispatcher import WebhookEventDispatcher

log = logging.getLogger(__name__)


dispatcher = WebhookEventDispatcher._registered_dispatcher
bp = sanic.Blueprint("Twitchio Webhooks", url_prefix="/webhooks")


@bp.route('/streams', ['GET'])
async def handle_stream_changed_get(request: request.Request):
    """Route receiving the challenge requests for the topic StreamChanged

    Parameters
    ----------
    request: sanic.request.Request
        The challenge request received from Twitch
    """
    return dispatcher().accept_subscription(request, Topic.stream_changed)


@bp.route('/streams', ['POST'])
@remove_duplicates
@verify_payload
async def handle_stream_changed_post(request: request.Request):
    """Route receiving the notifications for the topic StreamChanged

    Parameters
    ----------
    request: sanic.request.Request
        The challenge request received from Twitch
    """
    return await dispatcher().bulk_process_notification(request, Topic.stream_changed)


@bp.route('/users', ['GET'])
async def handle_user_changed_get(request: request.Request):
    """Route receiving the challenge requests for the topic UserChanged

    Parameters
    ----------
    request: sanic.request.Request
        The challenge request received from Twitch
    """
    return dispatcher().accept_subscription(request, Topic.user_changed)


@bp.route('/users', ['POST'])
@remove_duplicates
@verify_payload
async def handle_user_changed_post(request: request.Request):
    """Route receiving the notifications for the topic UserChanged

    Parameters
    ----------
    request: sanic.request.Request
        The challenge request received from Twitch
    """
    return await dispatcher().bulk_process_notification(request, Topic.user_changed)


@bp.route('/users/follows', ['GET'])
async def handle_user_follows_get(request: request.Request):
    """Route receiving the challenge requests for the topic UserFollows

    Parameters
    ----------
    request: sanic.request.Request
        The challenge request received from Twitch
    """
    return dispatcher().accept_subscription(request, Topic.user_follows)


@bp.route('/users/follows', ['POST'])
@remove_duplicates
@verify_payload
async def handle_user_follows_post(request: request.Request):
    """Route receiving the notifications for the topic UserFollows

    Parameters
    ----------
    request: sanic.request.Request
        The challenge request received from Twitch
    """
    return await dispatcher().bulk_process_notification(request, Topic.user_follows)

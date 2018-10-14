# -*- coding: utf-8 -*-

"""
The MIT License (MIT)

Copyright (c) 2017-2018 TwitchIO

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
from collections import namedtuple
from typing import Union

import aiohttp

from .cooldowns import RateBucket
from .errors import TwitchHTTPException

Chatters = namedtuple('Chatters', ('count', 'all', 'vips', 'moderators', 'staff', 'admins', 'global_mods', 'viewers'))


class HTTPSession:
    BASE = 'https://api.twitch.tv/helix'

    def __init__(self, loop, **attrs):
        self._id = attrs.get('client_id')

        self._bucket = RateBucket(method='http')
        self._session = aiohttp.ClientSession(loop=loop, headers={'Client-ID': self._id})

    async def request(self, method, url, *, params = None, limit = None, **kwargs):
        data = []

        params = params or []
        url = f'{self.BASE}{url}'

        cursor = None

        def reached_limit():
            return limit and len(data) >= limit

        def get_limit():
            if limit is None:
                return '100'

            to_get = limit - len(data)
            return str(to_get) if to_get < 100 else '100'

        while not reached_limit():
            if cursor is not None:
                params.append(('after', cursor))

            params.append(('first', get_limit()))

            body, is_text = await self._request(method, url, params=params, **kwargs)

            if is_text:
                return body

            if not body['data']:
                break

            params.pop()  # remove the first param

            if cursor is not None:
                params.pop()

            data += body['data']

            try:
                cursor = body['pagination'].get('cursor', None)
            except KeyError:
                break

        return data

    async def _request(self, method, url, utilize_bucket = True, **kwargs):
        reason = None

        for attempt in range(5):
            if utilize_bucket and self._bucket.limited:
                await self._bucket.wait_reset()

            async with self._session.request(method, url, **kwargs) as resp:
                if 500 <= resp.status <= 504:
                    reason = resp.reason
                    await asyncio.sleep(2 ** attempt + 1)
                    continue

                if utilize_bucket:
                    reset = resp.headers.get('Ratelimit-Reset')
                    remaining = resp.headers.get('Ratelimit-Remaining')

                    self._bucket.update(reset=reset, remaining=remaining)

                if 200 <= resp.status < 300:
                    if resp.headers.get('content-type') == 'application/json':
                        return await resp.json(), False

                    return await resp.text(encoding='utf-8'), True

                if resp.status == 429:
                    reason = 'Ratelimit Reached'

                    if not utilize_bucket:  # non Helix APIs don't have ratelimit headers
                        await asyncio.sleep(3 ** attempt + 1)
                    continue

                raise TwitchHTTPException(f'Failed to fulfil request ({resp.status}).', resp.reason)

        raise TwitchHTTPException('Failed to reach Twitch API', reason)

    @staticmethod
    def _populate_entries(*channels: Union[str, int]):
        names = set()
        ids = set()

        for channel in channels:
            if isinstance(channel, str):
                if channel.isdigit():
                    # Handle ids in the string form
                    ids.add(int(channel))
                else:
                    names.add(channel)
            elif isinstance(channel, int):
                ids.add(str(channel))

        if len(names | ids) > 100:
            raise TwitchHTTPException('Bad Request - Total entries must not exceed 100.')

        return names, ids

    async def get_users(self, *users: Union[str, int]):
        names, ids = self._populate_entries(*users)
        params = [('id', x) for x in ids] + [('login', x) for x in names]

        return await self.request('GET', '/users', params=params)

    async def get_followers(self, user_id: str):
        params = [('to_id', user_id)]
        return await self.request('GET', '/users/follows', params=params)

    async def get_following(self, user_id: str):
        params = [('from_id', user_id)]
        return await self.request('GET', '/users/follows', params=params)

    async def get_streams(self, *, game_id = None, language = None, channels, limit = None):
        if channels:
            names, ids = self._populate_entries(*channels)
            params = [('id', x) for x in ids] + [('user_login', x) for x in names]
        else:
            params = []

        if game_id is not None:
            params.append(('game_id', str(game_id)))

        if language is not None:
            params.append(('language', language))

        return await self.request('GET', '/streams', params=params, limit=limit)

    async def get_games(self, *games: Union[str, int]):
        names, ids = self._populate_entries(*games)
        params = [('id', x) for x in ids] + [('name', x) for x in names]

        return await self.request('GET', '/games', params=params)

    async def get_top_games(self, limit = None):
        return await self.request('GET', '/games/top', limit=limit)

    async def modify_webhook_subscription(self, *, callback, mode, topic, lease_seconds, secret = None):
        data = {
            'hub.callback': callback,
            'hub.mode': mode,
            'hub.topic': topic,
            'hub.lease_seconds': lease_seconds
        }

        if secret is not None:
            data['secret'] = secret

        return await self.request('POST', '/webhooks/hub', json=data)

    async def get_chatters(self, channel: str):
        url = f'http://tmi.twitch.tv/group/user/{channel}/chatters'

        data = await self._request('GET', url, utilize_bucket=False)

        all_ = []
        for x in data[0]['chatters'].values():
            all_ += x

        return Chatters(data[0]['chatter_count'], all_, *data[0]['chatters'].values())

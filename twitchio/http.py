# -*- coding: utf-8 -*-

"""
The MIT License (MIT)

Copyright (c) 2017-2019 TwitchIO

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
import aiohttp
import asyncio
import logging
from typing import Union

from .cooldowns import RateBucket
from .errors import HTTPException, Unauthorized


log = logging.getLogger(__name__)


class HTTPSession:
    BASE = 'https://api.twitch.tv/helix'
    TOKEN_BASE = "https://id.twitch.tv/oauth2/token"

    def __init__(self, loop, **attrs):
        self.client_id = client_id = attrs.get('client_id', None)
        self.client_secret = attrs.get("client_secret", None)
        self.token = attrs.get("api_token", None)
        self.scopes = attrs.get("scopes", [])

        if not client_id:
            log.warning('Running without client ID, HTTP endpoints will not work without authentication.')

        if not self.token and not client_id:
            log.warning("Running without client ID or bearer token, HTTP endpoints will not work without authentication.")

        self._bucket = RateBucket(method='http')
        self._session = aiohttp.ClientSession(loop=loop)
        self._refresh_token = None

    async def generate_token(self):
        if not self.client_id or not self.client_secret:
            raise HTTPException("Unable to generate a token, client id and/or client secret not given")

        if self._refresh_token:
            url = self.TOKEN_BASE + "?grant_type=refresh_token&refresh_token={0}&client_id={1}&client_secret={2}".format(
                self._refresh_token, self.client_id, self.client_secret)

        else:
            url = self.TOKEN_BASE + "?client_id={0}&client_secret={1}&grant_type=client_credentials".format(self.client_id, self.client_secret)
            if self.scopes:
                url += "&scope=" + " ".join(self.scopes)

        async with self._session.post(url) as resp:
            if 300 < resp.status or resp.status < 200:
                raise HTTPException("Unable to generate a token: " + await resp.text())

            data = await resp.json()
            self.token = data['access_token']
            self._refresh_token = data.get('refresh_token', None)
            logging.info("Invalid or no token found, generated new token")

    async def request(self, method, url, *, params=None, limit=None, **kwargs):
        count = kwargs.pop('count', False)

        data = []

        params = params or []
        url = f'{self.BASE}{url}'

        # headers = {}

        headers = kwargs.pop('headers', {})

        if self.client_id is not None:
            headers['Client-ID'] = str(self.client_id)

        if self.client_secret and self.client_id and not self.token:
            logging.info("No token passed, generating new token using client id and secret")
            await self.generate_token()

        if self.token is not None:
            headers['Authorization'] = "Bearer " + self.token

        #else: we'll probably get a 401, but we can check this in the response

        cursor = None

        def reached_limit():
            return limit and len(data) >= limit

        def get_limit():
            if limit is None:
                return '100'

            to_get = limit - len(data)
            return str(to_get) if to_get < 100 else '100'

        is_finished = False
        while not is_finished:
            if limit is not None:
                if cursor is not None:
                    params.append(('after', cursor))

                params.append(('first', get_limit()))

            body, is_text = await self._request(method, url, params=params, headers=headers, **kwargs)
            if is_text:
                return body

            if count:
                return body['total']

            params.pop()  # remove the first param

            if cursor is not None:
                params.pop()

            data += body['data']

            try:
                cursor = body['pagination'].get('cursor', None)
            except KeyError:
                break
            else:
                if not cursor:
                    break

            is_finished = reached_limit() if limit is not None else True

        return data

    async def _request(self, method, url, utilize_bucket=True, **kwargs):
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
                    if resp.content_type == 'application/json':
                        return await resp.json(), False

                    return await resp.text(encoding='utf-8'), True

                if resp.status == 401:
                    if self.client_id is None:
                        raise Unauthorized('A client ID and Bearer token is needed to use this route.')

                    if "WWW-Authenticate" in resp.headers:
                        try:
                            await self.generate_token()
                        except:
                            raise Unauthorized("Your oauth token is invalid, and a new one could not be generated")

                    raise Unauthorized('You\'re not authorized to use this route.')

                if resp.status == 429:
                    reason = 'Ratelimit Reached'

                    if not utilize_bucket:  # non Helix APIs don't have ratelimit headers
                        await asyncio.sleep(3 ** attempt + 1)
                    continue

                raise HTTPException(f'Failed to fulfil request ({resp.status}).', resp.reason)

        raise HTTPException('Failed to reach Twitch API', reason)

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
            raise HTTPException('Bad Request - Total entries must not exceed 100.')

        return names, ids

    async def get_users(self, *users: Union[str, int]):
        names, ids = self._populate_entries(*users)
        params = [('id', x) for x in ids] + [('login', x) for x in names]

        return await self.request('GET', '/users', params=params)

    async def get_follow(self, from_id: str, to_id: str):
        params = [('from_id', from_id), ('to_id', to_id)]
        return await self.request('GET', '/users/follows', params=params)

    async def get_followers(self, user_id: str, *, count):
        params = [('to_id', user_id)]
        return await self.request('GET', '/users/follows', params=params, count=count)

    async def get_following(self, user_id: str, *, count):
        params = [('from_id', user_id)]
        return await self.request('GET', '/users/follows', params=params, count=count)

    async def get_streams(self, *, game_id=None, language=None, channels, limit=None):
        if channels:
            names, ids = self._populate_entries(*channels)
            params = [('user_id', x) for x in ids] + [('user_login', x) for x in names]
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

    async def get_top_games(self, limit=None):
        return await self.request('GET', '/games/top', limit=limit)

    async def modify_webhook_subscription(self, *, callback, mode, topic, lease_seconds, secret=None):
        data = {
            'hub.callback': callback,
            'hub.mode': mode,
            'hub.topic': topic,
            'hub.lease_seconds': lease_seconds
        }

        if secret is not None:
            data['secret'] = secret

        return await self.request('POST', '/webhooks/hub', json=data)

    async def create_clip(self, token: str, broadcaster_id: int):
        params = [('broadcaster_id', str(broadcaster_id))]
        return await self.request('POST', '/clips', params=params, headers={'Authorization': f'Bearer {token}'})

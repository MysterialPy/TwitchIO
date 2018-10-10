import asyncio
import time
from typing import Union

import aiohttp

from .errors import TwitchHTTPException


class Bucket:
    LIMIT = 30

    def __init__(self):
        self.tokens = 0
        self._reset = time.time() + 60

    @property
    def limited(self):
        return self.tokens == self.LIMIT

    def reset(self):
        self.tokens = 0
        self._reset = time.time() + 60

    def update(self, *, reset=None, remaining=None):
        now = time.time()

        if self._reset <= now:
            self.reset()

        if reset:
            self._reset = int(reset)

        if remaining:
            self.tokens = self.LIMIT - int(remaining)
        else:
            self.tokens += 1

    async def wait_reset(self):
        now = time.time()

        await asyncio.sleep(self._reset - now)
        self.reset()


class HelixHTTPSession:
    BASE = 'https://api.twitch.tv/helix'

    def __init__(self, loop, **attrs):
        self._id = attrs.get('client_id')

        self._bucket = Bucket()
        self._session = aiohttp.ClientSession(loop=loop, headers={'Client-ID': self._id})

    async def request(self, method, url, *, params=None, limit=None, **kwargs):
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

    async def _request(self, method, url, **kwargs):
        reason = None

        for attempt in range(5):
            if self._bucket.limited:
                await self._bucket.wait_reset()

            async with self._session.request(method, url, **kwargs) as resp:
                if 500 <= resp.status <= 504:
                    reason = resp.reason
                    await asyncio.sleep(2 ** attempt + 1)
                    continue

                reset = resp.headers.get('Ratelimit-Reset')
                remaining = resp.headers.get('Ratelimit-Remaining')

                self._bucket.update(reset=reset, remaining=remaining)

                if 200 <= resp.status < 300:
                    if resp.headers.get('content-type') == 'application/json':
                        return await resp.json(), False

                    return await resp.text(encoding='utf-8'), True

                if resp.status == 429:
                    reason = 'Ratelimit Reached'
                    continue  # the Bucket will handle waiting

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

    async def get_followers(self, channel: str):
        raise NotImplementedError

    async def get_streams(self, *, game_id=None, language=None, channels, limit=None):
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

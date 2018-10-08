import aiohttp
import time
from typing import Union

from .errors import TwitchHTTPException


BASE = 'https://api.twitch.tv/helix/'
BASE5 = 'https://api.twitch.tv/kraken/'


class RateBucket:

    def __init__(self):
        self.tokens = 30
        self.refresh = time.time()

    def update_tokens(self):
        current = time.time()

        if self.tokens == 30:
            self.refresh = current + 60
        elif self.refresh <= current:
            self.tokens = 30
            self.refresh = current + 60

        self.tokens -= 1

        if self.tokens == 0:
            raise Exception(f'Rate limit exceeded please try again in {self.refresh - current}s')
        else:
            return self.tokens


rates = RateBucket()


def update_bucket(func):
    async def wrapper(*args, **kwargs):
        rates.update_tokens()

        return await func(*args, **kwargs)
    return wrapper


class HTTPSession:
    """Rewrite Session (Will soon be the only Session)"""

    def __init__(self, loop, **attrs):
        self._id = attrs.get('client_id')
        self._session = aiohttp.ClientSession(loop=loop, headers={'Client-ID': self._id}, raise_for_status=True)

    async def _get(self, url: str):
        error_message = f'Error retrieving API data \'{url}\''
        try:
            body = await (await self._session.get(url)).json()
            if 'pagination' in body:
                cursor = body['pagination'].get('cursor')
                while cursor:
                    next_url = url + f'&after={cursor}'
                    next_body = await(await self._session.get(next_url)).json()
                    body['data'] += next_body['data']
                    cursor = next_body['pagination'].get('cursor')
            return body
        except aiohttp.ClientResponseError as e:
            # HTTP errors
            raise TwitchHTTPException(f'{error_message} - Status {e.code}')
        except aiohttp.ClientError:
            # aiohttp errors
            raise TwitchHTTPException(error_message)

    @staticmethod
    def _populate_channels(*channels: Union[str, int]):
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
                ids.add(channel)

        if len(names | ids) > 100:
            raise TwitchHTTPException('Bad Request - Total channels must not exceed 100.')

        return names, ids

    @update_bucket
    async def _get_users(self, *users: Union[str, int]):
        names, ids = self._populate_channels(*users)

        ids = [f'id={c}' for c in ids]
        names = [f'login={c}' for c in names]

        args = "&".join(ids + names)
        url = BASE + f'users?{args}'

        return await self._get(url)

    @update_bucket
    async def _get_chatters(self, channel: str):
        channel = channel.lower()
        url = f'http://tmi.twitch.tv/group/user/{channel}/chatters'
        return await self._get(url)

    async def _get_followers(self, channel: str):
        raise NotImplementedError

    @update_bucket
    async def _get_stream_by_id(self, channel: int):
        url = BASE + f'streams?user_id={channel}'
        return await self._get(url)

    @update_bucket
    async def _get_stream_by_name(self, channel: str):
        url = BASE + f'streams?user_login={channel}'
        return await self._get(url)

    @update_bucket
    async def _get_streams(self, *channels: Union[str, int]):
        names, ids = self._populate_channels(*channels)

        ids = [f'user_id={c}' for c in ids]
        names = [f'user_login={c}' for c in names]

        args = "&".join(ids + names)
        url = BASE + f'streams?{args}'

        return await self._get(url)


"""
def _check_cid(func):
    def deco(inst, *args, **kwargs):
        if not inst._cid:
            raise TwitchHTTPException('Client ID is required to access this endpoint.')
        return func(inst, *args, **kwargs)
    return deco
    
    
class HttpSession:
    # Legacy Session (deprecated)

    def __init__(self, session, **attrs):
        self._aiosess = session
        self._api_token = attrs.get('apitok', None)
        self._cid = attrs.get('cid', None)

        if self._api_token:
            self._theaders = {'Client-ID': self._cid}  # TODO
        else:
            self._theaders = {'Client-ID': self._cid}

    async def fetch(self, url: str, headers: dict = None, timeout: float = None,
                    return_type: str = None, **kwargs):

        async with self._aiosess.get(url, headers=headers, timeout=timeout, **kwargs) as resp:
            if return_type:
                cont = getattr(resp, return_type)
                return resp, await cont()
            else:
                return resp, None

    async def poster(self, url: str, headers: dict = None, timeout: float = None,
                     return_type: str = None, **kwargs):

        async with self._aiosess.post(url, headers=headers, timeout=timeout, **kwargs) as resp:
            if return_type:
                cont = getattr(resp, return_type)
                return resp, await cont()
            else:
                return resp, None

    # TODO Error Handling
    @_check_cid
    async def _get_streams(self, channels):

        cid = set()
        cname = set()

        for chan in channels:
            try:
                chan = int(chan)
            except (TypeError, ValueError):
                cname.add(chan)
            else:
                cid.add(chan)

        if len(cid) + len(cname) > 100:
            raise TwitchHTTPException('Bad Request:: Total channels must not exceed 100.')

        logins = '&user_login='.join(c for c in cname)
        cids = '&user_id='.join(c for c in cid)
        streams = logins + cids

        url = BASE + 'streams?user_login={}'.format(streams)

        try:
            resp, cont = await self.fetch(url, timeout=10, return_type='json', headers=self._theaders)
        except Exception as e:
            return TwitchHTTPException('There was a problem with your request. {}'.format(e))

        if not resp.status == 200:
            raise TwitchHTTPException('{}:: There was a problem with your request. Try again.'.format(resp.status))

        cursor = cont['pagination']
        if not cursor:
            if not cont['data']:
                return None
            return cont

        data = {'data': []}
        for d in cont['data']:
            data['data'].append(d)

        while True:
            url = BASE + 'streams?after={}'.format(cursor)

            try:
                resp, cont = await self.fetch(url, timeout=10, return_type='json', headers=self._theaders)
            except Exception:
                break

            if resp.status > 200:
                break
            elif not cont['data']:
                break
            else:
                cursor = cont['pagination']

            for d in cont['data']:
                data['data'].append(d)

        return data

    # TODO Error Handling
    @_check_cid
    async def _get_stream(self, channel):

        try:
            channel = int(channel)
        except (TypeError, ValueError):
            user_url = BASE + 'streams?user_login={}'.format(channel)
        else:
            user_url = BASE + 'streams?user_id={}'.format(channel)

        try:
            resp, cont = await self.fetch(user_url, timeout=10, return_type='json', headers=self._theaders)
        except Exception as e:
            return TwitchHTTPException('There was a problem with your request. {}'.format(e))

        if not resp.status == 200:
            raise TwitchHTTPException('{}:: There was a problem with your request. Try again.'.format(resp.status))

        return cont

    @_check_cid
    async def _get_followers(self, channel):
        # Todo Error Handling
        if not self._api_token:
            return

        channel = await self._get_stream(channel)

        url = BASE + 'follows?first=100?to_id={}'.format(channel['data'][0]['id'])

        try:
            resp, cont = await self.fetch(BASE.format(url), timeout=5, return_type='json', headers=self._theaders)
        except Exception as e:
            return TwitchHTTPException('There was a problem with your request. {}'.format(e))

        if len(resp['data']) > 99:
            pass
"""

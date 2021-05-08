import datetime
import hmac
import hashlib
import logging
from typing import Dict, TYPE_CHECKING, Optional, Type, Union

from aiohttp import web

from ... import CustomReward, PartialUser

if TYPE_CHECKING:
    from .server import EventSubClient

try:
    import ujson as json
    def _loads(s: str) -> dict:
        return json.loads(s)
except ModuleNotFoundError:
    import json
    def _loads(s: str) -> dict:
        return json.loads(s)

logger = logging.getLogger("twitchio.ext.eventsub")


class EmptyObject:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Subscription:
    __slots__ = "id", "status", "type", "version", "cost", "condition", "transport", "created_at"
    def __init__(self, data: dict):
        self.id: str = data['id']
        self.status: str = data['status']
        self.type: str = data['type']
        self.version = int(data['version'])
        self.cost: int = data['cost']
        self.condition: Dict[str, str] = data['condition']
        self.created_at = datetime.datetime.strptime(data['created_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.transport = EmptyObject()
        self.transport.method: str = data['transport']['method'] # noqa
        self.transport.callback: str = data['transport']['callback'] # noqa


class Headers:
    def __init__(self, request: web.Request):
        self.message_id: str = request.headers['Twitch-Eventsub-Message-Id']
        self.message_retry: int = int(request.headers['Twitch-Eventsub-Message-Retry'])
        self.message_type: str = request.headers['Twitch-Eventsub-Message-Type']
        self.signature: str = request.headers['Twitch-Eventsub-Message-Signature']
        self.subscription_type: str = request.headers['Twitch-Eventsub-Subscription-Type']
        self.subscription_version: str = request.headers['Twitch-Eventsub-Subscription-Version']
        self.timestamp = datetime.datetime.strptime(
            request.headers['Twitch-Eventsub-Message-Timestamp'],
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._raw_timestamp = request.headers['Twitch-Eventsub-Message-Timestamp']


class BaseEvent:
    __slots__ = "_client", "_raw_data", "subscription", "headers"

    def __init__(self, client: "EventSubClient", data: str, request: web.Request):
        self._client = client
        self._raw_data = data
        data = _loads(data)
        self.subscription = Subscription(data['subscription'])
        self.headers = Headers(request)
        self.setup(data)

    def setup(self, data: dict):
        pass

    def verify(self):
        hmac_message = self.headers.message_id + self.headers._raw_timestamp + self._raw_data
        secret = self._client.secret.encode('utf-8')
        digest = hmac.new(secret, msg=hmac_message, digestmod=hashlib.sha256).hexdigest()

        if not hmac.compare_digest(digest, self.headers.signature[7:]):
            logger.warning(f"Recieved a message with an invalid signature, discarding.")
            return web.Response(status=400)

        return web.Response(status=200)


class RevokationEvent(BaseEvent):
    pass


class ChallengeEvent(BaseEvent):
    __slots__ = "challenge",

    def setup(self, data: dict):
        self.challenge: str = data['challenge']

    def verify(self):
        hmac_message = self.headers.message_id + self.headers._raw_timestamp + self._raw_data
        secret = self._client.secret.encode('utf-8')
        digest = hmac.new(secret, msg=hmac_message, digestmod=hashlib.sha256).hexdigest()

        if not hmac.compare_digest(digest, self.headers.signature[7:]):
            logger.warning(f"Recieved a message with an invalid signature, discarding.")
            return web.Response(status=400)

        return web.Response(status=200, text=self.challenge)


class NotificationEvent(BaseEvent):
    __slots__ = "data",

    def setup(self, data: dict):
        typ = self.subscription.type
        if typ not in SubscriptionTypes._type_map:
            raise ValueError(f"Unexpected subscription type '{typ}'")

        self.data: "_DataType" = SubscriptionTypes._type_map[typ](self._client, data)


def _transform_user(client: "EventSubClient", data: dict, field: str) -> PartialUser:
    return client.client.create_user(int(data[field+"_id"]), data[field+"_name"])


class EventData:
    __slots__ = ()


class ChannelBanData(EventData):
    __slots__ = "user", "broadcaster", "moderator", "reason", "ends_at", "permenant"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.moderator = _transform_user(client, data, "moderator_user")
        self.reason: str = data['reason']
        self.ends_at: Optional[datetime.datetime] = data['ends_at'] and \
                                                    datetime.datetime.strptime(data['ends_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.permenant: bool = data['permenant']


class ChannelSubscribeData(EventData):
    __slots__ = "user", "broadcaster", "tier", "is_gift"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.tier = int(data['tier'])
        self.is_gift: bool = data['is_gift']


class ChannelCheerData(EventData):
    __slots__ = "user", "broadcaster", "is_anonymous", "message", "bits"
    def __init__(self, client: "EventSubClient", data: dict):
        self.is_anonymous: bool = data['is_anonymous']
        self.user: Optional["PartialUser"] = self.is_anonymous and _transform_user(client, data, "user")
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.message: str = data['message']
        self.bits = int(data['bits'])


class ChannelUpdateData(EventData):
    __slots__ = "broadcaster", "title", "language", "category_id", "category_name", "is_mature"
    def __init__(self, client: "EventSubClient", data: dict):
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.title: str = data['title']
        self.language: str = data['language']
        self.category_id: str = data['category_id']
        self.category_name: str = data['category_name']
        self.is_mature = data['is_mature'] == "true"


class ChannelUnbanData(EventData):
    __slots__ = "user", "broadcaster", "moderator"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.moderator = _transform_user(client, data, "moderator_user")


class ChannelFollowData(EventData):
    __slots__ = "user", "broadcaster", "followed_at"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.followed_at = datetime.datetime.strptime(data['followed_at'], "%Y-%m-%dT%H:%M:%SZ")


class ChannelRaidData(EventData):
    __slots__ = "raider", "reciever", "viewer_count"
    def __init__(self, client: "EventSubClient", data: dict):
        self.raider = _transform_user(client, data, "from_broadcaster_user")
        self.reciever = _transform_user(client, data, "to_broadcaster_user")
        self.viewer_count = data['viewers']


class ChannelModeratorAddRemoveData(EventData):
    __slots__ = "broadcaster", "user"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.broadcaster = _transform_user(client, data, "broadcaster_user")

class CustomRewardAddUpdateRemoveData(EventData):
    __slots__ = "reward", "broadcaster", "id"
    def __init__(self, client: "EventSubClient", data: dict):
        self.id: str = data['id']
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.reward = CustomReward(client.client._http, data, self.broadcaster)

class CustomRewardRedemptionAddUpdateData(EventData):
    __slots__ = "broadcaster", "id", "user", "input", "status", "reward", "redeemed_at"
    def __init__(self, client: "EventSubClient", data: dict):
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.user = _transform_user(client, data, "user")
        self.id: str = data['id']
        self.input: str = data['user_input']
        self.status: str = data['status'] # "Possible values are unknown, unfulfilled, fulfilled, and canceled."
        self.redeemed_at = datetime.datetime.strptime(data['redeemed_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.reward = CustomReward(client.client._http, data['reward'], self.broadcaster)


class HypeTrainContributor:
    __slots__ = "user", "type", "total"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.type: str = data['type'] # one of bits, subscription
        self.total: int = data['total']


class HypeTrainBeginProgressData(EventData):
    __slots__ = "broadcaster", "total_points", "progress", "goal", "top_contributions", "last_contribution", "started", "expires"
    def __init__(self, client: "EventSubClient", data: dict):
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.total_points: int = data['total']
        self.progress: int = data['progress']
        self.goal: int = data['goal']
        self.started = datetime.datetime.strptime(data['started_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.expires = datetime.datetime.strptime(data['expire_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.top_contributions = [HypeTrainContributor(client, d) for d in data['top_contributions']]
        self.last_contribution = HypeTrainContributor(client, data['last_contribution'])


class HypeTrainEndData(EventData):
    __slots__ = "broadcaster", "level", "total_points", "top_contributions", "started", "ended", "cooldown_ends_at"
    def __init__(self, client: "EventSubClient", data: dict):
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.total_points: int = data['total']
        self.level: int = data['level']
        self.started = datetime.datetime.strptime(data['started_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.ended = datetime.datetime.strptime(data['ended_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.cooldown_ends_at = datetime.datetime.strptime(data['cooldown_ends_at'], "%Y-%m-%dT%H:%M:%SZ")
        self.top_contributions = [HypeTrainContributor(client, d) for d in data['top_contributions']]


class StreamOnlineData(EventData):
    __slots__ = "broadcaster", "id", "type", "started_at"
    def __init__(self, client: "EventSubClient", data: dict):
        self.broadcaster = _transform_user(client, data, "broadcaster_user")
        self.id: str = data['id']
        self.type: str = data['type'] # Valid values are: live, playlist, watch_party, premiere, rerun.
        self.started_at = datetime.datetime.strptime(data['started_at'], "%Y-%m-%dT%H:%M:%SZ")


class StreamOfflineData(EventData):
    __slots__ = "broadcaster",
    def __init__(self, client: "EventSubClient", data: dict):
        self.broadcaster = _transform_user(client, data, "broadcaster_user")


class UserAuthorizationRevokedData(EventData):
    __slots__ = "client_id", "user"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.client_id: str = data['client_id']


class UserUpdateData(EventData):
    __slots__ = "user", "email", "description"
    def __init__(self, client: "EventSubClient", data: dict):
        self.user = _transform_user(client, data, "user")
        self.email: Optional[str] = data['email']
        self.description: str = data['description']


_DataType = Union[
    ChannelBanData,
    ChannelUnbanData,
    ChannelSubscribeData,
    ChannelCheerData,
    ChannelUpdateData,
    ChannelFollowData,
    ChannelRaidData,
    ChannelModeratorAddRemoveData,
    CustomRewardAddUpdateRemoveData,
    CustomRewardRedemptionAddUpdateData,
    HypeTrainBeginProgressData,
    HypeTrainEndData,
    StreamOnlineData,
    StreamOfflineData,
    UserAuthorizationRevokedData,
    UserUpdateData
]


class _SubTypesMeta(type):
    def __new__(mcs, clsname, bases, attributes):
        attributes['_type_map'] = {
            args[0]: args[2] for name, args in attributes.items() if not name.startswith("_")
        }
        attributes['_name_map'] = {
            args[0]: args[2] for name, args in attributes.items() if not name.startswith("_")
        }
        return super().__new__(mcs, clsname, bases, attributes)

class _SubscriptionTypes(metaclass=_SubTypesMeta):
    _type_map: Dict[str, Type[_DataType]]
    _name_map: Dict[str, str]

    follow = "channel.follow", 1, ChannelFollowData
    subscription = "channel.subscribe", 1, ChannelSubscribeData
    cheer = "channel.cheer", 1, ChannelCheerData
    raid = "channel.raid", 1, ChannelRaidData
    ban = "chnnel.ban", 1, ChannelBanData
    unban = "channel.unban", 1, ChannelUnbanData

    channel_update = "channel.update", 1, ChannelUpdateData
    channel_moderator_add = "channel.moderator.add", 1, ChannelModeratorAddRemoveData
    channel_moderator_remove = "channel.moderator.remove", 1, ChannelModeratorAddRemoveData
    channel_reward_add = "channel.channel_points_custom_reward.add", 1, CustomRewardAddUpdateRemoveData
    channel_reward_update = "channel.channel_points_custom_reward.update", 1, CustomRewardAddUpdateRemoveData
    channel_reward_remove = "channel.channel_points_custom_reward.remove", 1, CustomRewardAddUpdateRemoveData
    channel_reward_redeem = "channel.channel_points_custom_reward_redemption.add", 1, CustomRewardRedemptionAddUpdateData
    channel_reward_redeem_updated = "channel.channel_points_custom_reward_redemption.update", 1, CustomRewardRedemptionAddUpdateData

    hypetrain_begin = "channel.hype_train.begin", 1, HypeTrainBeginProgressData
    hypetrain_progress = "channel.hype_train.progress", 1, HypeTrainBeginProgressData
    hypetrain_end = "channel.hype_train.end", 1, HypeTrainEndData

    stream_start = "stream.online", 1, StreamOnlineData
    stream_end = "stream.offline", 1, StreamOfflineData

    user_authorization_revoke = "user.authorization.revoke", 1, UserAuthorizationRevokedData

    user_update = "user.update", 1, UserUpdateData

SubscriptionTypes = _SubscriptionTypes()
import asyncio
import logging
import socket
from typing import Union, Tuple, Type, Optional, Any
from collections.abc import Iterable

import yarl
from aiohttp import web

from ... import Client, PartialUser
from . import models, http

try:
    from ssl import SSLContext
except:
    SSLContext = Any

__all__ = (
    "EventSubClient",
)

logger = logging.getLogger("twitchio.ext.eventsub")

_message_types = {
    "webhook_callback_verification": models.ChallengeEvent,
    "notification": models.NotificationEvent,
    "revokation": models.RevokationEvent
}


class EventSubClient(web.Application):
    def __init__(self, client: Client, webhook_secret: str, callback_route: str):
        self.client = client
        self.secret = webhook_secret
        self.route = callback_route
        self._http = http.EventSubHTTP(self)
        super(EventSubClient, self).__init__()
        self.router.add_post(yarl.URL(self.route).path, self._callback)
        self._closing = asyncio.Event()

    async def listen(self, **kwargs):
        self._closing.clear()
        await self.client.loop.create_task(self._run_app(**kwargs))

    def stop(self):
        self._closing.set()

    async def delete_subscription(self, subscription_id: str):
        await self._http.delete_subscription(subscription_id)

    async def get_subscriptions(self, status: str=None):
        # All possible statuses are:
        #
        #     enabled: designates that the subscription is in an operable state and is valid.
        #     webhook_callback_verification_pending: webhook is pending verification of the callback specified in the subscription creation request.
        #     webhook_callback_verification_failed: webhook failed verification of the callback specified in the subscription creation request.
        #     notification_failures_exceeded: notification delivery failure rate was too high.
        #     authorization_revoked: authorization for user(s) in the condition was revoked.
        #     user_removed: a user in the condition of the subscription was removed.
        return await self._http.get_subscriptions(status)

    async def subscribe_user_updated(self, user: Union[PartialUser, str, int]):
        if isinstance(user, PartialUser):
            user = user.id

        user = str(user)
        return await self._http.create_subscription(models.SubscriptionTypes.user_update, {"user_id": user})

    async def subscribe_channel_raid(self, from_broadcaster: Union[PartialUser, str, int]=None, to_broadcaster: Union[PartialUser, str, int]=None):
        if (not from_broadcaster and not to_broadcaster) or (from_broadcaster and to_broadcaster):
            raise ValueError("Expected 1 of from_broadcaster or to_broadcaster")

        if from_broadcaster:
            who = "from_broadcaster_user_id"
            broadcaster = from_broadcaster
        else:
            who = "to_broadcaster_user_id"
            broadcaster = to_broadcaster

        if isinstance(broadcaster, PartialUser):
            broadcaster = broadcaster.id

        broadcaster = str(broadcaster)
        return await self._http.create_subscription(models.SubscriptionTypes.raid, {who: broadcaster})

    async def _subscribe_channel_points_reward(self, event, broadcaster: Union[PartialUser, str, int], reward_id: str=None):
        if isinstance(broadcaster, PartialUser):
            broadcaster = broadcaster.id

        broadcaster = str(broadcaster)
        data = {"broadcaster_user_id": broadcaster}
        if reward_id:
            data['reward_id'] = reward_id

        return await self._http.create_subscription(event, data)

    async def _subscribe_with_broadcaster(
            self, event: Tuple[str, int, Type[models._DataType]], broadcaster: Union[PartialUser, str, int]
    ):
        if isinstance(broadcaster, PartialUser):
            broadcaster = broadcaster.id

        broadcaster = str(broadcaster)
        return await self._http.create_subscription(event, {"broadcaster_user_id": broadcaster})

    def subscribe_channel_bans(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.ban, broadcaster)

    def subscribe_channel_unbans(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.unban, broadcaster)

    def subscribe_channel_subscriptions(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.subscription, broadcaster)

    def subscribe_channel_cheers(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.cheer, broadcaster)

    def subscribe_channel_update(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.user_update, broadcaster)

    def subscribe_channel_follows(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.follow, broadcaster)

    def subscribe_channel_moderators_add(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.channel_moderator_add, broadcaster)

    def subscribe_channel_moderators_remove(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.channel_moderator_remove, broadcaster)

    def subscribe_channel_hypetrain_begin(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.hypetrain_begin, broadcaster)

    def subscribe_channel_hypetrain_progress(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.hypetrain_progress, broadcaster)

    def subscribe_channel_hypetrain_end(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.hypetrain_end, broadcaster)

    def subscribe_channel_stream_start(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.stream_start, broadcaster)

    def subscribe_channel_stream_end(self, broadcaster: Union[PartialUser, str, int]):
        return self._subscribe_with_broadcaster(models.SubscriptionTypes.stream_end, broadcaster)

    def subscribe_channel_points_reward_added(self, broadcaster: Union[PartialUser, str, int], reward_id: str):
        return self._subscribe_channel_points_reward(models.SubscriptionTypes.channel_reward_add, broadcaster, reward_id)

    def subscribe_channel_points_reward_updated(self, broadcaster: Union[PartialUser, str, int], reward_id: str):
        return self._subscribe_channel_points_reward(models.SubscriptionTypes.channel_reward_update, broadcaster, reward_id)

    def subscribe_channel_points_reward_removed(self, broadcaster: Union[PartialUser, str, int], reward_id: str):
        return self._subscribe_channel_points_reward(models.SubscriptionTypes.channel_reward_remove, broadcaster, reward_id)

    def subscribe_channel_points_redeemed(self, broadcaster: Union[PartialUser, str, int], reward_id: str=None):
        return self._subscribe_channel_points_reward(models.SubscriptionTypes.channel_reward_redeem, broadcaster, reward_id)

    def subscribe_channel_points_redeem_updated(self, broadcaster: Union[PartialUser, str, int], reward_id: str=None):
        return self._subscribe_channel_points_reward(models.SubscriptionTypes.channel_reward_redeem_updated, broadcaster, reward_id)

    async def subscribe_user_authorization_revoked(self):
        return await self._http.create_subscription(models.SubscriptionTypes.user_authorization_revoke, {"client_id": self.client._http.client_id})

    async def _callback(self, request: web.Request) -> web.Response:
        payload = await request.text()
        typ = request.headers.get("Twitch-Eventsub-Message-Type", "")
        if not typ:
            return web.Response(status=404)

        if typ not in _message_types:
            logger.warning(f"Unexpected message type: {typ}")
            return web.Response(status=400)

        event = _message_types[typ](self, payload, request)
        response = event.verify()

        if typ == "notification":
            self.client.run_event(f"eventsub_notification_{models.SubscriptionTypes._name_map[event.subscription.type]}", event)
        elif typ == "revokation":
            self.client.run_event("eventsub_revokation", event)

        return response

    async def _run_app(
            self,
            *,
            host: Optional[Union[str, web.HostSequence]] = None,
            port: Optional[int] = None,
            path: Optional[str] = None,
            sock: Optional[socket.socket] = None,
            shutdown_timeout: float = 60.0,
            ssl_context: Optional[SSLContext] = None,
            backlog: int = 128,
            access_log_class: Type[web.AbstractAccessLogger] = web.AccessLogger,
            access_log_format: str = web.AccessLogger.LOG_FORMAT,
            access_log: Optional[logging.Logger] = web.access_logger,
            handle_signals: bool = True,
            reuse_address: Optional[bool] = None,
            reuse_port: Optional[bool] = None,
        ) -> None:
        # This function is pulled from aiohttp.web._run_app
        app = self

        runner = web.AppRunner(
            app,
            handle_signals=handle_signals,
            access_log_class=access_log_class,
            access_log_format=access_log_format,
            access_log=access_log,
        )

        await runner.setup()

        sites = []

        try:
            if host is not None:
                if isinstance(host, (str, bytes, bytearray, memoryview)):
                    sites.append(
                        web.TCPSite(
                            runner,
                            host,
                            port,
                            shutdown_timeout=shutdown_timeout,
                            ssl_context=ssl_context,
                            backlog=backlog,
                            reuse_address=reuse_address,
                            reuse_port=reuse_port,
                        )
                    )
                else:
                    for h in host:
                        sites.append(
                            web.TCPSite(
                                runner,
                                h,
                                port,
                                shutdown_timeout=shutdown_timeout,
                                ssl_context=ssl_context,
                                backlog=backlog,
                                reuse_address=reuse_address,
                                reuse_port=reuse_port,
                            )
                        )
            elif path is None and sock is None or port is not None:
                sites.append(
                    web.TCPSite(
                        runner,
                        port=port,
                        shutdown_timeout=shutdown_timeout,
                        ssl_context=ssl_context,
                        backlog=backlog,
                        reuse_address=reuse_address,
                        reuse_port=reuse_port,
                    )
                )

            if path is not None:
                if isinstance(path, (str, bytes, bytearray, memoryview)):
                    sites.append(
                        web.UnixSite(
                            runner,
                            path,
                            shutdown_timeout=shutdown_timeout,
                            ssl_context=ssl_context,
                            backlog=backlog,
                        )
                    )
                else:
                    for p in path:
                        sites.append(
                            web.UnixSite(
                                runner,
                                p,
                                shutdown_timeout=shutdown_timeout,
                                ssl_context=ssl_context,
                                backlog=backlog,
                            )
                        )

            if sock is not None:
                if not isinstance(sock, Iterable):
                    sites.append(
                        web.SockSite(
                            runner,
                            sock,
                            shutdown_timeout=shutdown_timeout,
                            ssl_context=ssl_context,
                            backlog=backlog,
                        )
                    )
                else:
                    for s in sock:
                        sites.append(
                            web.SockSite(
                                runner,
                                s,
                                shutdown_timeout=shutdown_timeout,
                                ssl_context=ssl_context,
                                backlog=backlog,
                            )
                        )
            for site in sites:
                await site.start()

            names = sorted(str(s.name) for s in runner.sites)
            logger.debug("Running EventSub server on {}".format(", ".join(names)))

            await self._closing.wait()
        finally:
            await runner.cleanup()
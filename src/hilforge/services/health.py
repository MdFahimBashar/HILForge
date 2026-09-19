from __future__ import annotations

from redis import Redis
from redis.exceptions import RedisError


def redis_is_available(url: str) -> bool:
    client: Redis = Redis.from_url(
        url,
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )
    try:
        return bool(client.ping())
    except RedisError:
        return False
    finally:
        client.close()

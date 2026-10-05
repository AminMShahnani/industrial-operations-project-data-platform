import hashlib

from redis import Redis
from redis.exceptions import RedisError

from operations.contracts import ServiceError


class RequestLimiter:
    def __init__(self, redis: Redis, maximum: int = 600) -> None:
        self.redis = redis
        self.maximum = maximum

    def check(self, address: str) -> None:
        # Server-owned Lua atomically establishes expiry; no customer expressions execute.
        key = "iop:auth-rate:" + hashlib.sha256(address.encode()).hexdigest()
        try:
            count = self.redis.eval(
                "local n = redis.call('INCR', KEYS[1]); "
                "if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end; return n",
                1,
                key,
            )
        except RedisError as error:
            raise ServiceError(503, "rate_limit_unavailable") from error
        if not isinstance(count, int):
            raise ServiceError(503, "rate_limit_unavailable")
        if count > self.maximum:
            raise ServiceError(429, "rate_limit_exceeded")

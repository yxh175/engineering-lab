local now = redis.call('TIME')
return {now[1], now[2], redis.call('GET', KEYS[1]) or false,
    redis.call('PTTL', KEYS[1]), redis.call('GET', KEYS[2]) or false}

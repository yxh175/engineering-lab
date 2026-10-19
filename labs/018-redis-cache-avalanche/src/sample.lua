local now = redis.call('TIME')
local rows = {}
for i, key in ipairs(KEYS) do
    rows[i] = {key, redis.call('GET', key) or false, redis.call('PTTL', key)}
end
return {now[1], now[2], rows}

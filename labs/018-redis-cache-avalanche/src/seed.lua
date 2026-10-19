local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local rows = {}
for i, key in ipairs(KEYS) do
    local ttl = tonumber(ARGV[i])
    local deadline = now_ms + ttl
    local result = redis.call('SET', key, 'cached:' .. key, 'PXAT', deadline)
    rows[i] = {key, ttl, deadline, result.ok, redis.call('PTTL', key)}
end
return {now[1], now[2], rows}

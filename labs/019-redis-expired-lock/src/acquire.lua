if redis.call('EXISTS', KEYS[1]) == 1 then
    return {0, 0}
end
local fence = redis.call('INCR', KEYS[2])
local result = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2])
if not result then
    return {0, 0}
end
return {1, fence}

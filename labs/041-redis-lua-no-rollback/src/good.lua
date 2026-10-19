local kind=redis.call('TYPE',KEYS[2]).ok
if kind~='none' and kind~='list' then
    return redis.error_reply('DEST_NOT_LIST')
end
redis.call('SET',KEYS[1],'1')
redis.call('LPUSH',KEYS[2],ARGV[1])
redis.call('SET',KEYS[3],'1')
return 1

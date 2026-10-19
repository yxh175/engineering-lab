redis.call('SET',KEYS[1],'1')
redis.call('LPUSH',KEYS[2],ARGV[1])
redis.call('SET',KEYS[3],'1')
return 1

local keys=redis.call('KEYS','lab042:*')
table.sort(keys)
local values=redis.call('MGET',unpack(keys))
local ttl=redis.call('PTTL','lab042:sentinel')
local memory=redis.call('INFO','memory')
local stats=redis.call('INFO','stats')
return {keys,values,ttl,memory,stats}

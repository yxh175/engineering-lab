package main

import "sync"

type Object struct {
	ID    uint64 `json:"id"`
	Value int64  `json:"value"`
}

// Required data has explicit ownership until deletion or replacement.
type Cache struct {
	mu     sync.RWMutex
	values map[string]*Object
}

func (c *Cache) Put(key string, value *Object) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.values == nil {
		c.values = make(map[string]*Object)
	}
	c.values[key] = value
}

func (c *Cache) Get(key string) (*Object, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	v, ok := c.values[key]
	return v, ok
}

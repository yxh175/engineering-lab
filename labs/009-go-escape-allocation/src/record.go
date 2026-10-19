package main

type Record struct{ A, B, C uint64 }

var pointerSink *Record
var valueSink Record
var interfaceSink any
var checksumSink uint64

func newPointer(i uint64) *Record {
	r := Record{i, i*3 + 7, i ^ 0x5A5A}
	return &r
}

func newValue(i uint64) Record {
	return Record{i, i*3 + 7, i ^ 0x5A5A}
}

//go:noinline
func newNoInlinePointer(i uint64) *Record {
	r := Record{i, i*3 + 7, i ^ 0x5A5A}
	return &r
}

func runPointerLocal(n int) uint64 {
	var sum uint64
	for i := 0; i < n; i++ {
		r := newPointer(uint64(i))
		sum += r.A + r.B + r.C
	}
	return sum
}

func runPointerRetained(n int) uint64 {
	var sum uint64
	for i := 0; i < n; i++ {
		r := newPointer(uint64(i))
		pointerSink = r
		sum += r.A + r.B + r.C
	}
	return sum
}

func runValueRetained(n int) uint64 {
	var sum uint64
	for i := 0; i < n; i++ {
		r := newValue(uint64(i))
		valueSink = r
		sum += r.A + r.B + r.C
	}
	return sum
}

func runNoInlinePointerLocal(n int) uint64 {
	var sum uint64
	for i := 0; i < n; i++ {
		r := newNoInlinePointer(uint64(i))
		sum += r.A + r.B + r.C
	}
	return sum
}

func runInterfaceLocal(n int) uint64 {
	var sum uint64
	for i := 0; i < n; i++ {
		var box any = newValue(uint64(i))
		r := box.(Record)
		sum += r.A + r.B + r.C
	}
	return sum
}

func runInterfaceRetained(n int) uint64 {
	var sum uint64
	for i := 0; i < n; i++ {
		interfaceSink = newValue(uint64(i))
		r := interfaceSink.(Record)
		sum += r.A + r.B + r.C
	}
	return sum
}

var runners = map[string]func(int) uint64{
	"PointerLocal":         runPointerLocal,
	"PointerRetained":      runPointerRetained,
	"ValueRetained":        runValueRetained,
	"NoInlinePointerLocal": runNoInlinePointerLocal,
	"InterfaceLocal":       runInterfaceLocal,
	"InterfaceRetained":    runInterfaceRetained,
}

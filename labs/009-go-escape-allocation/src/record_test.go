package main

import "testing"

func benchmarkRecords(b *testing.B, runner func(int) uint64) {
	b.ReportAllocs()
	b.ResetTimer()
	sum := runner(b.N)
	b.StopTimer()
	checksumSink = sum
	b.Logf("CHECKSUM n=%d value=%d", b.N, sum)
}

func BenchmarkPointerLocal(b *testing.B) {
	benchmarkRecords(b, runPointerLocal)
}
func BenchmarkPointerRetained(b *testing.B) {
	benchmarkRecords(b, runPointerRetained)
}
func BenchmarkValueRetained(b *testing.B) {
	benchmarkRecords(b, runValueRetained)
}
func BenchmarkNoInlinePointerLocal(b *testing.B) {
	benchmarkRecords(b, runNoInlinePointerLocal)
}
func BenchmarkInterfaceLocal(b *testing.B) {
	benchmarkRecords(b, runInterfaceLocal)
}
func BenchmarkInterfaceRetained(b *testing.B) {
	benchmarkRecords(b, runInterfaceRetained)
}

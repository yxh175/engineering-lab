#define _POSIX_C_SOURCE 200809L
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#define ITERATIONS UINT64_C(400000000)
typedef struct { uint64_t seed, result, iterations; } Job;
static void *compute(void *arg) {
    Job *j=arg;
    uint64_t x=j->seed;
    for (uint64_t i=0; i<ITERATIONS; i++) {
        x=x*UINT64_C(1664525)+UINT64_C(1013904223);
        x ^= x>>13;
    }
    j->result=x; j->iterations=ITERATIONS;
    return NULL;
}
static uint64_t tick(clockid_t id) {
    struct timespec t;
    if (clock_gettime(id, &t)) { perror("clock"); exit(1); }
    return (uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint64_t)t.tv_nsec;
}
static void copy(const char *from, const char *to) {
    FILE *in=fopen(from,"r"), *out=fopen(to,"w");
    if (!in || !out) { perror("open"); exit(1); }
    char b[4096]; size_t n;
    while ((n=fread(b,1,sizeof b,in))) {
        if (fwrite(b,1,n,out)!=n) { perror("write"); exit(1); }
    }
    if (ferror(in) || fclose(out)) { perror("copy"); exit(1); }
    fclose(in);
}
int main(void) {
    copy("/sys/fs/cgroup/cpu.max","/out/cpu.max");
    copy("/sys/fs/cgroup/cpuset.cpus.effective","/out/cpuset.cpus.effective");
    copy("/sys/fs/cgroup/memory.max","/out/memory.max");
    copy("/sys/fs/cgroup/cpu.stat","/out/before-cpu.stat");
    Job jobs[2]={{.seed=1},{.seed=2}};pthread_t threads[2];
    uint64_t cpu0=tick(CLOCK_PROCESS_CPUTIME_ID), wall0=tick(CLOCK_MONOTONIC);
    for (int i=0;i<2;i++) if (pthread_create(&threads[i],NULL,compute,&jobs[i])) return 2;
    for (int i=0;i<2;i++) if (pthread_join(threads[i],NULL)) return 3;
    uint64_t wall=tick(CLOCK_MONOTONIC)-wall0, cpu=tick(CLOCK_PROCESS_CPUTIME_ID)-cpu0;
    copy("/sys/fs/cgroup/cpu.stat","/out/after-cpu.stat");
    char report[1024];
    snprintf(report,sizeof report,
      "{\"threads\":2,\"iterations\":[%" PRIu64 ",%" PRIu64 "],"
      "\"results\":[\"%" PRIu64 "\",\"%" PRIu64 "\"],"
      "\"wall_ns\":%" PRIu64 ",\"process_cpu_ns\":%" PRIu64 ",\"online_cpus\":%ld}\n",
      jobs[0].iterations,jobs[1].iterations,jobs[0].result,jobs[1].result,wall,cpu,sysconf(_SC_NPROCESSORS_ONLN));
    FILE *f=fopen("/out/report.json","w");if (!f) return 4;
    fputs(report,f);if (fclose(f)) return 5;fputs(report,stdout);
    return 0;
}

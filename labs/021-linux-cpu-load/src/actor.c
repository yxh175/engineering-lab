#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

static void line(const char *text) {
    size_t n = strlen(text);
    if (write(STDOUT_FILENO, text, n) != (ssize_t)n) _exit(70);
}
static void byte(char expected) {
    char value = 0;
    ssize_t n;
    do { n = read(STDIN_FILENO, &value, 1); } while (n < 0 && errno == EINTR);
    if (n != 1 || value != expected) _exit(71);
}
struct child_arg { pid_t parent; };
static int child(void *ptr) {
    const struct child_arg *arg = ptr;
    char text[160];
    snprintf(text, sizeof(text), "{\"stage\":\"child\",\"pid\":%d,\"child_pid\":%d}\n", (int)arg->parent, (int)getpid());
    line(text);
    byte('R'); // child is in interruptible pipe read; parent waits for child's mm release
    _exit(0);
}
static long long us(const struct timeval *t) { return (long long)t->tv_sec * 1000000 + t->tv_usec; }
int main(int argc, char **argv) {
    if (argc != 2) return 64;
    const char *mode = argv[1];
    if (strcmp(mode, "cpu-busy") && strcmp(mode, "pipe-read") && strcmp(mode, "clone-wait")) return 64;
    char text[320];
    snprintf(text, sizeof(text), "{\"stage\":\"ready\",\"pid\":%d,\"ppid\":%d,\"mode\":\"%s\"}\n", (int)getpid(), (int)getppid(), mode);
    line(text);byte('G'); // common start gate, followed by explicit release R
    uint64_t iterations = 0, checksum = 1;
    pid_t child_pid = 0;
    if (!strcmp(mode, "cpu-busy")) {
        int flags = fcntl(STDIN_FILENO, F_GETFL);
        if (flags < 0 || fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK) < 0) return 72;
        for (;;) {
            for (int i = 0; i < 8192; i++) { checksum = checksum * 1664525 + 1013904223; iterations++; }
            char value = 0;ssize_t n = read(STDIN_FILENO, &value, 1);
            if (n == 1 && value == 'R') break;
            if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR) || n == 1) return 73;
        }
    } else if (!strcmp(mode, "pipe-read")) {
        byte('R');
    } else {
        // glibc clone wrapper supplies a separate child stack: this is not a vfork() C continuation.
        void *stack = malloc(65536);if (!stack) return 74;
        struct child_arg arg = {.parent = getpid()};
        child_pid = clone(child, (char *)stack + 65536, CLONE_VM | CLONE_VFORK | SIGCHLD, &arg);
        if (child_pid < 0) { perror("clone");return 75; }
        int status = -1;
        if (waitpid(child_pid, &status, 0) != child_pid || !WIFEXITED(status) || WEXITSTATUS(status) != 0) return 76;
        free(stack);
    }
    struct rusage self, children;
    if (getrusage(RUSAGE_SELF, &self) || getrusage(RUSAGE_CHILDREN, &children)) return 77;
    snprintf(text, sizeof(text), "{\"stage\":\"done\",\"pid\":%d,\"child_pid\":%d,\"iterations\":%" PRIu64 ",\"checksum\":%" PRIu64 ",\"self_cpu_us\":%lld,\"children_cpu_us\":%lld}\n", (int)getpid(), (int)child_pid, iterations, checksum, us(&self.ru_utime)+us(&self.ru_stime), us(&children.ru_utime)+us(&children.ru_stime));
    line(text);return 0;
}

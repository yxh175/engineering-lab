#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void die(const char *s) { perror(s); exit(1); }
static void byte_write(int fd) { if (write(fd, "x", 1) != 1) die("write"); }
static void byte_read(int fd) { char b; if (read(fd, &b, 1) != 1) die("read"); }
static void copy(const char *from, const char *to) {
    FILE *in = fopen(from, "r");
    int err = errno;
    FILE *out = fopen(to, "w");
    if (!out) die("output");
    if (!in) fprintf(out, "OPEN_ERROR errno=%d\n", err);
    else {
        char b[4096]; size_t n;
        while ((n = fread(b, 1, sizeof b, in))) {
            if (fwrite(b, 1, n, out) != n) die("fwrite");
        }
        if (ferror(in)) die("fread");
        fclose(in);
    }
    if (fclose(out)) die("fclose");
}
static char state(pid_t pid) {
    char path[128], b[4096];
    snprintf(path, sizeof path, "/proc/%d/stat", pid);
    FILE *f = fopen(path, "r");
    if (!f) { if (errno != ENOENT) die("stat"); return '-'; }
    if (!fgets(b, sizeof b, f)) die("stat read");
    fclose(f);
    char *end = strrchr(b, ')');
    if (!end || end[1] != ' ') die("stat format");
    return end[2];
}
static void until_state(pid_t pid, char expected) {
    struct timespec delay = {.tv_sec=0, .tv_nsec=1000000};
    for (int i=0; i<2000; i++) {
        if (state(pid) == expected) return;
        nanosleep(&delay, NULL);
    }
    fprintf(stderr, "state deadline expected=%c\n", expected); exit(1);
}
static int snapshot(pid_t pid, const char *phase) {
    char path[128], out[128], id[32];
    const char *files[] = {"stat", "status", "wchan"};
    for (int i=0; i<3; i++) {
        snprintf(path, sizeof path, "/proc/%d/%s", pid, files[i]);
        snprintf(out, sizeof out, "/out/%s-%s.txt", phase, files[i]);
        copy(path, out);
    }
    snprintf(out, sizeof out, "/out/%s-ps.txt", phase);
    snprintf(id, sizeof id, "%d", pid);
    pid_t ps = fork();
    if (ps < 0) die("ps fork");
    if (ps == 0) {
        int fd=open(out, O_WRONLY|O_CREAT|O_TRUNC, 0644);
        if (fd<0 || dup2(fd, STDOUT_FILENO)<0 || dup2(fd, STDERR_FILENO)<0) _exit(126);
        close(fd);
        execlp("ps", "ps", "-o", "pid,ppid,stat,comm,args", "-p", id, (char *)NULL);
        _exit(127);
    }
    int status;
    if (waitpid(ps, &status, 0) != ps || !WIFEXITED(status)) die("ps wait");
    return WEXITSTATUS(status);
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const char *which = argv[1];
    int running = !strcmp(which, "running-control");
    int good = !strcmp(which, "immediate-wait");
    if (!running && !good && strcmp(which, "unreaped")) return 2;
    int ready[2], gate[2];
    if (pipe(ready) || pipe(gate)) die("pipe");
    pid_t child=fork();
    if (child<0) die("fork");
    if (child==0) {
        close(ready[0]); close(gate[1]);
        if (prctl(PR_SET_NAME, "lab044-child", 0, 0, 0)) _exit(125);
        byte_write(ready[1]); close(ready[1]);
        if (running) byte_read(gate[0]);
        close(gate[0]); _exit(42);
    }
    close(ready[1]); close(gate[0]);
    byte_read(ready[0]); close(ready[0]);
    until_state(child, running ? 'S' : 'Z');
    int status=0; pid_t waited=0;
    if (good) { waited=waitpid(child, &status, 0); if (waited!=child) die("wait good"); }
    char before=state(child);
    int before_ps=snapshot(child, "before");
    if (running) byte_write(gate[1]);
    close(gate[1]);
    if (!good) { waited=waitpid(child, &status, 0); if (waited!=child) die("wait final"); }
    char after=state(child);
    int after_ps=snapshot(child, "after");
    errno=0; pid_t twice=waitpid(child, &status, WNOHANG); int twice_errno=errno;
    copy("/sys/fs/cgroup/cpu.max", "/out/cpu.max");
    copy("/sys/fs/cgroup/memory.max", "/out/memory.max");
    char report[1024];
    snprintf(report, sizeof report,
        "{\"case\":\"%s\",\"parent\":%d,\"child\":%d,\"before\":\"%c\","
        "\"after\":\"%c\",\"before_ps_exit\":%d,\"after_ps_exit\":%d,"
        "\"wait_pid\":%d,\"wait_status\":%d,\"exited\":%s,\"exit_status\":%d,"
        "\"second_wait\":%d,\"second_errno\":%d}\n",
        which, getpid(), child, before, after, before_ps, after_ps, waited, status,
        WIFEXITED(status) ? "true":"false", WEXITSTATUS(status), twice, twice_errno);
    FILE *f=fopen("/out/report.json", "w"); if (!f) die("report");
    fputs(report, f); if (fclose(f)) die("report close");
    fputs(report, stdout);
    return 0;
}

"""Retain the actual Windows consumer process handle across launcher termination."""
import ctypes
from ctypes import wintypes

k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];k.GetExitCodeProcess.restype=wintypes.BOOL
k.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)];k.IsProcessInJob.restype=wintypes.BOOL
k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.WaitForSingleObject.restype=wintypes.DWORD
k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL

class ProcessHandle:
    def __init__(self,pid):
        self.pid=pid;self.handle=k.OpenProcess(0x1000|0x00100000,False,pid)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
    def state(self):
        code=wintypes.DWORD();job=wintypes.BOOL()
        if not k.GetExitCodeProcess(self.handle,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
        if not k.IsProcessInJob(self.handle,None,ctypes.byref(job)):raise ctypes.WinError(ctypes.get_last_error())
        return {'pid':self.pid,'exit_code':code.value,'in_job':bool(job.value)}
    def wait(self):
        result=k.WaitForSingleObject(self.handle,10000)
        assert result==0,{'wait_result':result,'pid':self.pid}
        return self.state()
    def close(self):
        assert k.CloseHandle(self.handle)

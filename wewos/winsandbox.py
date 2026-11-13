# Author: Michel Sanner, PhD. Copyright (c) 2026.
"""Isolated networks on Windows: an AppContainer in a Job object.

  AppContainer  Windows' own app sandbox (what Edge and Store apps run in).
                The worker gets an AppContainer of its own (one per network):
                it can read and write its network's folder (granted here),
                read the Python environment and WEWoS (granted once by
                `wewos sandbox-setup` to all app sandboxes), read the folders
                the user grants, and reach the internet only with the
                internetClient capability. Loopback to this machine is closed
                to app sandboxes by Windows.
  Job object    ends the worker and whatever it starts when the server ends
                (kill on job close), and on Force stop; limits its memory.

The read-only level has no counterpart here: a low-integrity process reads the
user's files, but closing its internet access needs administrator rights.

Everything Windows-specific is loaded inside the functions, so that this
module imports anywhere (its command builders are tested on Linux).
"""
import json
import os
import subprocess
import sys

ALL_APP_PACKAGES = 'S-1-15-2-1'          # every app sandbox
INTERNET_CLIENT = 'S-1-15-3-1'           # the internetClient capability
SETUP_FILE = os.path.join(os.path.expanduser('~'), '.wewos', 'sandbox-setup.json')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---- what must be readable, and the one-time setup ------------------------------------
def shared_read_paths():
    """The Python environment and WEWoS: every sandboxed network reads them."""
    out = []
    for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, REPO):
        p = os.path.realpath(p)
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def grant_command(path, sid, rights):
    """icacls command line granting a SID rights on a folder and what it holds
    (rights: RX read and run, F full)."""
    return ['icacls', path, '/grant', '*%s:(OI)(CI)%s' % (sid, rights), '/Q']


def remove_command(path, sid):
    return ['icacls', path, '/remove', '*%s' % sid, '/Q']


def setup_done():
    try:
        with open(SETUP_FILE) as fh:
            done = set(json.load(fh).get('granted', []))
    except (OSError, ValueError):
        return False
    return all(p in done for p in shared_read_paths())


def setup(echo=print):
    """wewos sandbox-setup: let app sandboxes read the Python environment and
    WEWoS (icacls, once; a large environment takes a minute)."""
    granted = []
    for p in shared_read_paths():
        echo('granting Windows app sandboxes read access to %s ...' % p)
        r = subprocess.run(grant_command(p, ALL_APP_PACKAGES, 'RX'), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise RuntimeError('icacls failed on %s: %s' % (p, r.stdout.decode('mbcs', 'replace').strip()))
        granted.append(p)
    os.makedirs(os.path.dirname(SETUP_FILE), exist_ok=True)
    with open(SETUP_FILE, 'w') as fh:
        json.dump({'granted': granted}, fh, indent=1)
    echo('done: networks can now run sandboxed on this machine')


def environment(folder):
    """The worker's environment on Windows: what Python and the C runtime need,
    its home and temporary files in its folder, none of the server's secrets."""
    home = os.path.join(folder, '.wewos')
    sysroot = os.environ.get('SYSTEMROOT', r'C:\Windows')
    path = [sys.prefix, os.path.join(sys.prefix, 'Library', 'bin'), os.path.join(sys.prefix, 'Scripts'),
            os.path.join(sys.base_prefix), os.path.join(sysroot, 'System32'), sysroot]
    env = {'PATH': os.pathsep.join(path), 'SYSTEMROOT': sysroot, 'WINDIR': sysroot,
           'PATHEXT': os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD'),
           'PYTHONPATH': REPO, 'PYTHONNOUSERSITE': '1', 'PYTHONIOENCODING': 'utf-8',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
           'USERPROFILE': home, 'HOME': home, 'APPDATA': home, 'LOCALAPPDATA': home,
           'TEMP': os.path.join(home, 'tmp'), 'TMP': os.path.join(home, 'tmp'),
           'MPLCONFIGDIR': os.path.join(home, 'matplotlib'), 'MPLBACKEND': 'Agg',
           'WEWOS_ISOLATION': 'sandboxed'}
    for k in ('NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OMP_NUM_THREADS',
              'OPENBLAS_NUM_THREADS', 'ADS_ROOT'):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def handle_args(args, fd_to_handle):
    """The worker's command line with the values of --rfd and --wfd (this
    process's file descriptors) replaced by the matching Windows handles."""
    m = {str(k): str(v) for k, v in fd_to_handle.items()}
    return [m.get(a, a) if i and args[i - 1] in ('--rfd', '--wfd') else a for i, a in enumerate(args)]


def container_name(sid):
    return 'WEWoS.network.%s' % sid[:16]


# ---- Windows API ----------------------------------------------------------------------------
_api = None


def _load():
    global _api
    if _api is not None:
        return _api
    import ctypes
    from ctypes import wintypes as wt

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [('Sid', ctypes.c_void_p), ('Attributes', wt.DWORD)]

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [('AppContainerSid', ctypes.c_void_p),
                    ('Capabilities', ctypes.POINTER(SID_AND_ATTRIBUTES)),
                    ('CapabilityCount', wt.DWORD), ('Reserved', wt.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
                    ('lpTitle', wt.LPWSTR), ('dwX', wt.DWORD), ('dwY', wt.DWORD),
                    ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
                    ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                    ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
                    ('lpReserved2', ctypes.c_void_p), ('hStdInput', wt.HANDLE),
                    ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [('StartupInfo', STARTUPINFOW), ('lpAttributeList', ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                    ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
            'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                    ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wt.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wt.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wt.DWORD),
                    ('SchedulingClass', wt.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ('IoInfo', IO_COUNTERS), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t)]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', wt.DWORD), ('dwMemoryLoad', wt.DWORD),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    uenv = ctypes.WinDLL('userenv', use_last_error=True)

    def sig(fn, res, *args):
        fn.restype, fn.argtypes = res, list(args)
        return fn

    api = type('api', (), {})()
    api.ctypes, api.wt = ctypes, wt
    api.SID_AND_ATTRIBUTES, api.SECURITY_CAPABILITIES = SID_AND_ATTRIBUTES, SECURITY_CAPABILITIES
    api.STARTUPINFOEXW, api.PROCESS_INFORMATION = STARTUPINFOEXW, PROCESS_INFORMATION
    api.JOBOBJECT_EXTENDED_LIMIT_INFORMATION = JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    api.MEMORYSTATUSEX = MEMORYSTATUSEX
    api.CreateAppContainerProfile = sig(uenv.CreateAppContainerProfile, ctypes.c_long, wt.LPCWSTR,
                                        wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD,
                                        ctypes.POINTER(ctypes.c_void_p))
    api.DeriveAppContainerSidFromAppContainerName = sig(
        uenv.DeriveAppContainerSidFromAppContainerName, ctypes.c_long, wt.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p))
    api.DeleteAppContainerProfile = sig(uenv.DeleteAppContainerProfile, ctypes.c_long, wt.LPCWSTR)
    api.FreeSid = sig(adv.FreeSid, ctypes.c_void_p, ctypes.c_void_p)
    api.ConvertSidToStringSidW = sig(adv.ConvertSidToStringSidW, wt.BOOL, ctypes.c_void_p,
                                     ctypes.POINTER(wt.LPWSTR))
    api.ConvertStringSidToSidW = sig(adv.ConvertStringSidToSidW, wt.BOOL, wt.LPCWSTR,
                                     ctypes.POINTER(ctypes.c_void_p))
    api.LocalFree = sig(k32.LocalFree, ctypes.c_void_p, ctypes.c_void_p)
    api.InitializeProcThreadAttributeList = sig(k32.InitializeProcThreadAttributeList, wt.BOOL,
                                                ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                                ctypes.POINTER(ctypes.c_size_t))
    api.UpdateProcThreadAttribute = sig(k32.UpdateProcThreadAttribute, wt.BOOL, ctypes.c_void_p,
                                        wt.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_void_p)
    api.DeleteProcThreadAttributeList = sig(k32.DeleteProcThreadAttributeList, None, ctypes.c_void_p)
    api.CreateProcessW = sig(k32.CreateProcessW, wt.BOOL, wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                             ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION))
    api.CreateJobObjectW = sig(k32.CreateJobObjectW, wt.HANDLE, ctypes.c_void_p, wt.LPCWSTR)
    api.SetInformationJobObject = sig(k32.SetInformationJobObject, wt.BOOL, wt.HANDLE, ctypes.c_int,
                                      ctypes.c_void_p, wt.DWORD)
    api.AssignProcessToJobObject = sig(k32.AssignProcessToJobObject, wt.BOOL, wt.HANDLE, wt.HANDLE)
    api.TerminateJobObject = sig(k32.TerminateJobObject, wt.BOOL, wt.HANDLE, wt.UINT)
    api.ResumeThread = sig(k32.ResumeThread, wt.DWORD, wt.HANDLE)
    api.TerminateProcess = sig(k32.TerminateProcess, wt.BOOL, wt.HANDLE, wt.UINT)
    api.CloseHandle = sig(k32.CloseHandle, wt.BOOL, wt.HANDLE)
    api.WaitForSingleObject = sig(k32.WaitForSingleObject, wt.DWORD, wt.HANDLE, wt.DWORD)
    api.GetExitCodeProcess = sig(k32.GetExitCodeProcess, wt.BOOL, wt.HANDLE, ctypes.POINTER(wt.DWORD))
    api.GlobalMemoryStatusEx = sig(k32.GlobalMemoryStatusEx, wt.BOOL, ctypes.POINTER(MEMORYSTATUSEX))
    _api = api
    return api


def _err(what):
    import ctypes
    code = ctypes.get_last_error()
    return OSError('%s failed: %s' % (what, ctypes.FormatError(code).strip() or code))


def memory_limit():
    """Three quarters of the machine's memory."""
    api = _load()
    m = api.MEMORYSTATUSEX()
    m.dwLength = api.ctypes.sizeof(m)
    if not api.GlobalMemoryStatusEx(api.ctypes.byref(m)):
        return None
    return int(m.ullTotalPhys * 0.75)


def container_sid(name):
    """The AppContainer of one network: (its SID as a pointer, as a string)."""
    api = _load()
    ctypes = api.ctypes
    sid = ctypes.c_void_p()
    hr = api.CreateAppContainerProfile(name, name, 'A WEWoS network', None, 0, ctypes.byref(sid))
    if hr & 0xFFFFFFFF == 0x800700B7:                       # it exists already
        hr = api.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    if hr != 0:
        raise OSError('could not create the app sandbox %s (HRESULT 0x%08X)' % (name, hr & 0xFFFFFFFF))
    text = api.wt.LPWSTR()
    if not api.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise _err('ConvertSidToStringSid')
    s = text.value
    api.LocalFree(text)
    return sid, s


def delete_container(name):
    try:
        _load().DeleteAppContainerProfile(name)
    except Exception:
        pass


class Process(object):
    """A worker started in an AppContainer: the calls IsolatedSession makes on
    a subprocess.Popen."""

    def __init__(self, hprocess, pid, job, stdout, name, sid_text, granted):
        self.hprocess, self.pid, self.job, self.stdout = hprocess, pid, job, stdout
        self.name, self.sid_text, self.granted = name, sid_text, granted
        self.returncode = None

    def poll(self):
        if self.returncode is None:
            api = _load()
            code = api.wt.DWORD()
            if api.GetExitCodeProcess(self.hprocess, api.ctypes.byref(code)) and code.value != 259:
                self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        api = _load()
        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if api.WaitForSingleObject(self.hprocess, ms) != 0:
            raise subprocess.TimeoutExpired('wewos worker', timeout)
        return self.poll()

    def kill(self):
        api = _load()
        if not api.TerminateJobObject(self.job, 1):
            api.TerminateProcess(self.hprocess, 1)

    def release(self):
        """The network is gone for good: its app sandbox and its grants too."""
        for path in self.granted:
            subprocess.run(remove_command(path, self.sid_text), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        delete_container(self.name)


def start(args, env, folder, pass_fds, name, internet, grants=()):
    """Start args in a new AppContainer named name, in a Job object, with the
    file descriptors pass_fds inherited (their handle numbers are what the
    worker is given). Returns a Process."""
    import msvcrt
    api = _load()
    ctypes, wt = api.ctypes, api.wt
    sid, sid_text = container_sid(name)
    granted = []
    # its folder, read and write; the folders the user grants, read
    for path, rights in [(folder, 'F')] + [(g, 'RX') for g in grants]:
        r = subprocess.run(grant_command(path, sid_text, rights), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise OSError('icacls could not open %s to the sandbox: %s'
                          % (path, r.stdout.decode('mbcs', 'replace').strip()))
        granted.append(path)
    # the handles it inherits: the pipes, its output, and NUL for its input
    out_r, out_w = os.pipe()
    nul = os.open('NUL', os.O_RDONLY)
    handles = [msvcrt.get_osfhandle(fd) for fd in list(pass_fds) + [out_w, nul]]
    for h in handles:
        os.set_handle_inheritable(h, True)
    # the worker is given the handles of the pipes, not this process's descriptors
    args = handle_args(args, dict(zip(pass_fds, handles)))
    caps = (api.SID_AND_ATTRIBUTES * 1)()
    capsid = ctypes.c_void_p()
    ncaps = 0
    if internet:
        if not api.ConvertStringSidToSidW(INTERNET_CLIENT, ctypes.byref(capsid)):
            raise _err('ConvertStringSidToSid')
        caps[0].Sid, caps[0].Attributes, ncaps = capsid.value, 0x4, 1   # SE_GROUP_ENABLED
    secaps = api.SECURITY_CAPABILITIES(sid.value, ctypes.cast(caps, ctypes.POINTER(api.SID_AND_ATTRIBUTES))
                                       if ncaps else None, ncaps, 0)
    size = ctypes.c_size_t()
    api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    attrs = ctypes.create_string_buffer(size.value)
    pattrs = ctypes.cast(attrs, ctypes.c_void_p)
    if not api.InitializeProcThreadAttributeList(pattrs, 2, 0, ctypes.byref(size)):
        raise _err('InitializeProcThreadAttributeList')
    hlist = (wt.HANDLE * len(handles))(*handles)
    try:
        if not api.UpdateProcThreadAttribute(pattrs, 0, 0x20009, ctypes.byref(secaps),      # SECURITY_CAPABILITIES
                                             ctypes.sizeof(secaps), None, None):
            raise _err('UpdateProcThreadAttribute (sandbox)')
        if not api.UpdateProcThreadAttribute(pattrs, 0, 0x20002, ctypes.byref(hlist),     # HANDLE_LIST
                                             ctypes.sizeof(hlist), None, None):
            raise _err('UpdateProcThreadAttribute (handles)')
        si = api.STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(si)
        si.StartupInfo.dwFlags = 0x100                                # STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput = handles[-1]
        si.StartupInfo.hStdOutput = si.StartupInfo.hStdError = handles[-2]
        si.lpAttributeList = pattrs.value
        block = ''.join('%s=%s\0' % kv for kv in sorted(env.items())) + '\0'
        envbuf = ctypes.create_unicode_buffer(block, len(block) + 1)
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        pi = api.PROCESS_INFORMATION()
        flags = 0x00080000 | 0x00000400 | 0x00000004 | 0x08000000     # extended startup info,
        #                                                            unicode environment, suspended, no window
        if not api.CreateProcessW(None, cmd, None, None, True, flags,
                                  ctypes.cast(envbuf, ctypes.c_void_p), folder,
                                  ctypes.byref(si), ctypes.byref(pi)):
            raise _err('CreateProcess in the app sandbox')
    except BaseException:
        os.close(out_r)
        raise
    finally:
        api.DeleteProcThreadAttributeList(pattrs)
        if ncaps:
            api.LocalFree(capsid)
        os.close(out_w)
        os.close(nul)
    job = api.CreateJobObjectW(None, None)
    info = api.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000                    # KILL_ON_JOB_CLOSE
    mem = memory_limit()
    if mem:
        info.BasicLimitInformation.LimitFlags |= 0x200                # JOB_MEMORY
        info.JobMemoryLimit = mem
    ok = job and api.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
        and api.AssignProcessToJobObject(job, pi.hProcess)
    if not ok:
        api.TerminateProcess(pi.hProcess, 1)
        raise _err('the job object of the sandbox')
    api.ResumeThread(pi.hThread)
    api.CloseHandle(pi.hThread)
    return Process(pi.hProcess, pi.dwProcessId, job, os.fdopen(out_r, 'rb'), name, sid_text, granted)

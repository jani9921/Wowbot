"""Selected-process lifetime via documented OS metadata; no memory reads."""
from __future__ import annotations


def retail_build(version_text):
    import re
    from .builds import VERIFIED_OPCODE_BUILDS
    match = re.search(r'(\d+)[.,\s]+(\d+)[.,\s]+(\d+)[.,\s(]+(\d+)', version_text or '')
    if not match or tuple(map(int, match.groups()[:2])) != (12, 1):
        raise ValueError('unsupported selected client version')
    build = int(match[4])
    if build not in VERIFIED_OPCODE_BUILDS:
        raise ValueError('selected client build has no reviewed opcode family')
    return build


def executable_build(path):
    import ctypes
    from ctypes import wintypes as w
    version = ctypes.WinDLL('version', use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
    version.GetFileVersionInfoSizeW.restype = w.DWORD
    version.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID]
    version.VerQueryValueW.argtypes = [w.LPCVOID, w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.UINT)]
    ignored = w.DWORD()
    size = version.GetFileVersionInfoSizeW(path, ctypes.byref(ignored))
    if not 0 < size <= 1024*1024:
        raise OSError('selected executable version resource unavailable')
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        raise OSError('selected executable version resource unreadable')
    pointer, length = ctypes.c_void_p(), w.UINT()
    if not version.VerQueryValueW(data, r'\VarFileInfo\Translation', ctypes.byref(pointer), ctypes.byref(length)):
        raise OSError('selected executable version translation unavailable')
    translations = ctypes.cast(pointer, ctypes.POINTER(w.WORD))
    for index in range(0, min(length.value//2, 32)-1, 2):
        key = f'\\StringFileInfo\\{translations[index]:04x}{translations[index+1]:04x}\\ProductVersion'
        text_pointer, text_length = ctypes.c_void_p(), w.UINT()
        if version.VerQueryValueW(data, key, ctypes.byref(text_pointer), ctypes.byref(text_length)):
            try:
                return retail_build(ctypes.wstring_at(text_pointer, min(text_length.value, 128)).rstrip('\0'))
            except ValueError:
                continue
    raise ValueError('selected executable build unknown or unsupported')


def selected_process_identity(pid):
    import ctypes
    from ctypes import wintypes as w
    from wowbot.session_context import ProcessIdentity
    if type(pid) is not int or pid <= 0:
        raise ValueError("selected PID required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)]*4)]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        raise OSError("selected process metadata unavailable")
    try:
        created, exited, kernel_time, user_time = (w.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise OSError("selected process creation time unavailable")
        generation = f"{created.dwHighDateTime:08x}{created.dwLowDateTime:08x}"
        size, path = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            raise OSError('selected process executable metadata unavailable')
        if path.value.rsplit('\\', 1)[-1].casefold() != 'wow.exe':
            raise ValueError('selected process is not the Retail WoW executable')
        return ProcessIdentity(pid, generation, executable_build(path.value))
    finally:
        kernel.CloseHandle(handle)

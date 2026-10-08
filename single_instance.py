import sys
import socket
import ctypes

ERROR_ALREADY_EXISTS = 183
IPC_PORT = 29173
MUTEX_NAME = "Local\\ScreenTranslator_SingleInstance_Mutex_v3"

_mutex_handle = None


def notify_primary_instance() -> bool:
    """Send trigger command to already running primary instance."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(("127.0.0.1", IPC_PORT))
        s.sendall(b"TRIGGER\n")
        s.close()
        return True
    except Exception:
        return False


def acquire_single_instance_lock() -> bool:
    """
    Enforces that only one instance of the application can run.
    If another instance is already running:
      - Wakes it up via IPC
      - Closes duplicate mutex handle
      - Returns False so current process can immediately exit
    If this is the first instance:
      - Keeps the mutex handle alive
      - Returns True
    """
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32

    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_err = kernel32.GetLastError()

    if last_err == ERROR_ALREADY_EXISTS:
        notify_primary_instance()
        if _mutex_handle:
            kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None
        return False

    return True


def release_single_instance_lock():
    """Release mutex handle on clean exit."""
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None

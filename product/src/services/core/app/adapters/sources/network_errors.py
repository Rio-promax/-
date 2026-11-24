import gzip
import ssl


def is_transient_network_error(error: BaseException) -> bool:
    reason = getattr(error, "reason", error)
    if isinstance(
        reason,
        (
            ssl.SSLError,
            ConnectionResetError,
            ConnectionAbortedError,
            TimeoutError,
            EOFError,
            gzip.BadGzipFile,
        ),
    ):
        return True
    text = str(reason).casefold()
    return any(
        marker in text
        for marker in (
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "unexpected eof",
            "eof occurred",
            "bad gzip",
            "incomplete or truncated",
        )
    )

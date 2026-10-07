import asyncio
import contextlib
import signal
import sys
from asyncio.subprocess import DEVNULL, PIPE, Process
from collections import deque
from collections.abc import Sequence

import structlog

log = structlog.get_logger(__name__)

FFMPEG_BIN = "ffmpeg"
BASE_ARGS = ["-hide_banner", "-nostats"]
STDERR_TAIL_LINES = 50


class FfmpegError(Exception):
    """ffmpeg exited with a non-zero code or timed out."""

    def __init__(self, rc: int | None, stderr: str) -> None:
        self.rc = rc
        self.stderr = stderr
        tail = stderr.strip()[-500:]
        super().__init__(f"ffmpeg failed (rc={rc}): {tail}")


class FfmpegTimeoutError(FfmpegError):
    """ffmpeg did not finish in time and was killed."""


async def _kill(proc: Process) -> None:
    """Hard-kill the process if it is still alive and reap it."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()


async def run(args: Sequence[str], *, timeout: float, loglevel: str = "error") -> tuple[int, str]:
    """Run a one-shot ffmpeg command and return (returncode, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        FFMPEG_BIN,
        *BASE_ARGS,
        "-loglevel",
        loglevel,
        "-nostdin",
        *args,
        stdin=DEVNULL,
        stdout=DEVNULL,
        stderr=PIPE,
    )
    try:
        async with asyncio.timeout(timeout):
            _, err = await proc.communicate()
    except TimeoutError:
        raise FfmpegTimeoutError(None, f"timed out after {timeout}s") from None
    finally:
        await _kill(proc)

    rc = proc.returncode
    assert rc is not None
    return rc, err.decode(errors="replace")


async def run_checked(args: Sequence[str], *, timeout: float, loglevel: str = "error") -> str:
    """Like run(), but raise FfmpegError on a non-zero exit code."""
    rc, stderr = await run(args, timeout=timeout, loglevel=loglevel)
    if rc != 0:
        raise FfmpegError(rc, stderr)
    return stderr


class FfmpegProcess:
    """Long-running ffmpeg process with continuous stderr draining."""

    def __init__(self, proc: Process) -> None:
        self._proc = proc
        self._tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._drain_task = asyncio.create_task(self._drain_stderr())

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    def stderr_tail(self) -> str:
        return "\n".join(self._tail)

    async def wait(self) -> int:
        rc = await self._proc.wait()
        await self._drain_task
        return rc

    async def stop(self, timeout: float = 5) -> int:
        if self._proc.returncode is None:
            self._interrupt()
            try:
                async with asyncio.timeout(timeout):
                    await self._proc.wait()
            except TimeoutError:
                log.warning("ffmpeg_stop_timeout", pid=self.pid, timeout=timeout)
            await _kill(self._proc)
        return await self.wait()

    def _interrupt(self) -> None:
        with contextlib.suppress(ProcessLookupError, BrokenPipeError, ConnectionResetError):
            if sys.platform == "win32":
                assert self._proc.stdin is not None
                self._proc.stdin.write(b"q")
            else:
                self._proc.send_signal(signal.SIGINT)

    async def _drain_stderr(self) -> None:
        stderr = self._proc.stderr
        assert stderr is not None
        try:
            async for raw in stderr:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    self._tail.append(line)
                    log.warning("ffmpeg_stderr", pid=self.pid, line=line)
        except ValueError:
            while await stderr.read(65536):
                pass


async def spawn(args: Sequence[str], *, loglevel: str = "warning") -> FfmpegProcess:
    proc = await asyncio.create_subprocess_exec(
        FFMPEG_BIN,
        *BASE_ARGS,
        "-loglevel",
        loglevel,
        *args,
        stdin=PIPE,
        stdout=DEVNULL,
        stderr=PIPE,
    )
    return FfmpegProcess(proc)

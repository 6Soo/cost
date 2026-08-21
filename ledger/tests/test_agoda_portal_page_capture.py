from __future__ import annotations

import contextlib
import hashlib
import json
import multiprocessing
import os

os.environ["AGODA_WINDOWS_UIA_IMPLEMENTATION"] = "powershell"

import subprocess
import unittest
import sqlite3
import tempfile
import time
import traceback
from pathlib import Path
from unittest.mock import call, patch

import tools.agoda_portal_page_capture as page_capture
import tools.agoda_portal_detail_capture as detail_capture
from tools.agoda_portal_page_capture import (
    CSC_PATH_DEFAULT,
    DATE_RE,
    EXPECTED_PAGE_ORDER,
    FRAMEWORK64_DIR_DEFAULT,
    WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS,
    WINDOWS_UIA_BRIDGE_SLOT_COUNT,
    WINDOWS_UIA_BRIDGE_SLOT_PATHS,
    WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS,
    WINDOWS_UIA_FOREGROUND_LOCK_PATH,
    WINDOWS_UIA_FOREGROUND_OPERATIONS,
    WINDOWS_UIA_LOCK_DIRECTORY,
    WINDOWS_UIA_MUTATING_OPERATIONS,
    _cleanup_compiled_bridge,
    _click,
    _element_name,
    _ensure_csharp_bridge,
    _extract_cards,
    _card_block_hash,
    capture_page,
    _go_to_page,
    _resolve_csharp_source_windows_path,
    _resolve_windows_temp_dir,
    _verify_csharp_bridge_executable,
    _wait_loaded,
    _wait_stable_page_tree,
    _wait_page_controls,
    _page_buttons,
    _special_buttons,
    _resolve_date,
    _run_windows_uia,
    _release_private_file_lock,
    _try_private_file_lock,
    _windows_uia_bridge_admission,
    _windows_uia_foreground_lock,
    _windows_uia_window_lock_path,
    capture_pages,
)


def _hold_windows_uia_lock(
    lock_path: str,
    entered: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    page_capture.WINDOWS_UIA_FOREGROUND_LOCK_PATH = Path(lock_path)
    page_capture.WINDOWS_UIA_FOREGROUND_LOCK_TIMEOUT_SECONDS = 5.0
    with page_capture._windows_uia_foreground_lock():
        entered.set()
        release.wait(5.0)


def _hold_windows_uia_bridge_slot(
    slot_paths: tuple[str, ...],
    entered: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
    active: object,
    max_active: object,
) -> None:
    page_capture.WINDOWS_UIA_BRIDGE_SLOT_PATHS = tuple(
        Path(path) for path in slot_paths
    )
    page_capture.WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS = 5.0
    page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS = 1.0
    page_capture.WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS = 0.005
    with page_capture._windows_uia_bridge_admission("state", "1"):
        with active.get_lock():
            active.value += 1
            max_active.value = max(max_active.value, active.value)
        entered.set()
        release.wait(5.0)
        with active.get_lock():
            active.value -= 1


def _hold_windows_uia_admission(
    lock_dir: str,
    operation: str,
    window_id: str,
    entered: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
    active: object,
    max_active: object,
) -> None:
    directory = Path(lock_dir)
    page_capture.WINDOWS_UIA_LOCK_DIRECTORY = directory
    page_capture.WINDOWS_UIA_FOREGROUND_LOCK_PATH = directory / "foreground.lock"
    page_capture.WINDOWS_UIA_BRIDGE_SLOT_PATHS = tuple(
        directory / f"bridge-slot-{index}.lock"
        for index in range(5)
    )
    page_capture.WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS = 5.0
    page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS = 1.0
    page_capture.WINDOWS_UIA_FOREGROUND_LOCK_TIMEOUT_SECONDS = 5.0
    page_capture.WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS = 0.005
    with page_capture._windows_uia_bridge_admission(operation, window_id):
        with active.get_lock():
            active.value += 1
            max_active.value = max(max_active.value, active.value)
        entered.set()
        release.wait(5.0)
        with active.get_lock():
            active.value -= 1


class AgodaPortalPageCaptureTests(unittest.TestCase):
    def test_windows_uia_focus_operations_take_bridge_admission(self) -> None:
        response = {"ok": True, "result": {"action": "focus"}}
        entries: list[str] = []

        class RecordingAdmission:
            def __init__(self, operation: str, window_id: str) -> None:
                self.operation = operation
                self.window_id = window_id

            def __enter__(self) -> float:
                entries.append(f"enter:{self.operation}:{self.window_id}")
                return 7.5

            def __exit__(self, *_args: object) -> None:
                entries.append(f"exit:{self.operation}:{self.window_id}")

        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            side_effect=lambda operation, window_id, **kwargs: RecordingAdmission(
                operation, window_id
            ),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response)
            _run_windows_uia(
                "computer", "hotkey", "--window-id", "1", "--key", "CmdOrCtrl+L"
            )
            _run_windows_uia(
                "computer", "type-text", "--window-id", "1", "--text", "url"
            )
            _run_windows_uia(
                "computer", "press-key", "--window-id", "1", "--key", "Return"
            )

        self.assertEqual(
            entries,
            [
                "enter:hotkey:1",
                "exit:hotkey:1",
                "enter:type:1",
                "exit:type:1",
                "enter:press:1",
                "exit:press:1",
            ],
        )
        self.assertTrue(all(item.kwargs["timeout"] == 7.5 for item in run.call_args_list))

    def test_windows_uia_nonfocus_operations_also_take_bridge_admission(self) -> None:
        response = {"ok": True, "result": {"snapshot": {"treeText": ""}}}
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(6.0),
        ) as admission, patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response)
            _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        admission.assert_called_once()
        self.assertEqual(admission.call_args[0], ("state", "1"))

    def test_windows_uia_focus_rolls_back_partial_lock_set_before_retry(
        self,
    ) -> None:
        with patch(
            "tools.agoda_portal_page_capture._try_windows_uia_bridge_slot",
            side_effect=[10, 11],
        ), patch(
            "tools.agoda_portal_page_capture._try_private_file_lock",
            side_effect=[20, None, 21, 22],
        ), patch(
            "tools.agoda_portal_page_capture._release_private_file_lock"
        ) as release, patch(
            "tools.agoda_portal_page_capture._bounded_lock_sleep",
            return_value=True,
        ):
            with _windows_uia_bridge_admission("press", "1") as remaining:
                self.assertGreater(remaining, 0)

        self.assertEqual(
            release.call_args_list,
            [call(20), call(10), call(22), call(21), call(11)],
        )

    def test_windows_uia_bridge_slot_count_and_private_paths_configuration(
        self,
    ) -> None:
        self.assertEqual(WINDOWS_UIA_BRIDGE_SLOT_COUNT, 5)
        self.assertEqual(len(WINDOWS_UIA_BRIDGE_SLOT_PATHS), 5)
        for slot_no, path in enumerate(WINDOWS_UIA_BRIDGE_SLOT_PATHS):
            self.assertEqual(path.parent, WINDOWS_UIA_LOCK_DIRECTORY)
            self.assertEqual(path.name, f"bridge-slot-{slot_no}.lock")

    def test_windows_uia_bridge_admission_caps_five_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            slot_paths = tuple(
                str(Path(directory) / f"slot-{index}.lock")
                for index in range(5)
            )
            context = multiprocessing.get_context("fork")
            entered = [context.Event() for _ in range(6)]
            release = [context.Event() for _ in range(6)]
            active = context.Value("i", 0)
            max_active = context.Value("i", 0)
            processes = [
                context.Process(
                    target=_hold_windows_uia_bridge_slot,
                    args=(slot_paths, entered[index], release[index], active, max_active),
                )
                for index in range(6)
            ]
            try:
                for process in processes[:5]:
                    process.start()
                for event in entered[:5]:
                    self.assertTrue(event.wait(2.0))
                processes[5].start()
                time.sleep(0.2)
                self.assertFalse(entered[5].is_set())
                release[0].set()
                self.assertTrue(entered[5].wait(2.0))
                self.assertEqual(max_active.value, 5)
            finally:
                for event in release:
                    event.set()
                for process in processes:
                    if process.pid is None:
                        continue
                    process.join(2.0)
                    if process.is_alive():
                        process.terminate()
                        process.join(2.0)

    def test_windows_uia_bridge_admission_skips_busy_slot_and_times_out_when_full(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            slot_paths = tuple(
                Path(directory) / f"slot-{index}.lock" for index in range(5)
            )
            with patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_SLOT_PATHS",
                slot_paths,
            ):
                first = _try_private_file_lock(slot_paths[0])
                self.assertIsNotNone(first)
                try:
                    with _windows_uia_bridge_admission("state", "1"):
                        pass
                finally:
                    _release_private_file_lock(first)

                held = [_try_private_file_lock(path) for path in slot_paths]
                self.assertTrue(all(item is not None for item in held))
                try:
                    with patch(
                        "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS",
                        0.05,
                    ), patch(
                        "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS",
                        0.01,
                    ), patch(
                        "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS",
                        0.005,
                    ):
                        with self.assertRaisesRegex(
                            RuntimeError,
                            "windows UIA bridge admission timed out",
                        ):
                            with _windows_uia_bridge_admission("state", "1"):
                                self.fail("all occupied slots must not admit")
                finally:
                    for descriptor in held:
                        _release_private_file_lock(descriptor)

                with _windows_uia_bridge_admission("state", "1"):
                    pass

    def test_windows_uia_same_hwnd_click_select_mutual_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("fork")
            entered = [context.Event() for _ in range(2)]
            release = [context.Event() for _ in range(2)]
            active = context.Value("i", 0)
            max_active = context.Value("i", 0)
            p1 = context.Process(
                target=_hold_windows_uia_admission,
                args=(directory, "click", "100", entered[0], release[0], active, max_active),
            )
            p2 = context.Process(
                target=_hold_windows_uia_admission,
                args=(directory, "select", "100", entered[1], release[1], active, max_active),
            )
            try:
                p1.start()
                self.assertTrue(entered[0].wait(2.0))
                p2.start()
                time.sleep(0.2)
                self.assertFalse(entered[1].is_set())
                release[0].set()
                self.assertTrue(entered[1].wait(2.0))
                self.assertEqual(max_active.value, 1)
            finally:
                for event in release:
                    event.set()
                for process in (p1, p2):
                    if process.pid is None:
                        continue
                    process.join(2.0)
                    if process.is_alive():
                        process.terminate()
                        process.join(2.0)

    def test_windows_uia_different_hwnd_mutations_proceed_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("fork")
            count = 5
            entered = [context.Event() for _ in range(count)]
            release = [context.Event() for _ in range(count)]
            active = context.Value("i", 0)
            max_active = context.Value("i", 0)
            operations = ["click", "select", "click", "select", "click"]
            processes = [
                context.Process(
                    target=_hold_windows_uia_admission,
                    args=(
                        directory,
                        operations[index],
                        str(101 + index),
                        entered[index],
                        release[index],
                        active,
                        max_active,
                    ),
                )
                for index in range(count)
            ]
            try:
                for process in processes:
                    process.start()
                for event in entered:
                    self.assertTrue(event.wait(2.0))
                self.assertEqual(max_active.value, count)
            finally:
                for event in release:
                    event.set()
                for process in processes:
                    if process.pid is None:
                        continue
                    process.join(2.0)
                    if process.is_alive():
                        process.terminate()
                        process.join(2.0)

    def test_windows_uia_foreground_operation_concurrency_remains_strictly_one(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("fork")
            entered = [context.Event() for _ in range(3)]
            release = [context.Event() for _ in range(3)]
            active = context.Value("i", 0)
            max_active = context.Value("i", 0)
            ops = [("hotkey", "101"), ("type", "102"), ("press", "103")]
            processes = [
                context.Process(
                    target=_hold_windows_uia_admission,
                    args=(
                        directory,
                        ops[index][0],
                        ops[index][1],
                        entered[index],
                        release[index],
                        active,
                        max_active,
                    ),
                )
                for index in range(3)
            ]
            try:
                processes[0].start()
                self.assertTrue(entered[0].wait(2.0))
                processes[1].start()
                processes[2].start()
                time.sleep(0.2)
                self.assertFalse(entered[1].is_set())
                self.assertFalse(entered[2].is_set())
                release[0].set()
                self.assertTrue(
                    any([entered[1].wait(2.0), entered[2].wait(2.0)])
                )
                self.assertEqual(max_active.value, 1)
                if entered[1].is_set():
                    release[1].set()
                    self.assertTrue(entered[2].wait(2.0))
                else:
                    release[2].set()
                    self.assertTrue(entered[1].wait(2.0))
                self.assertEqual(max_active.value, 1)
            finally:
                for event in release:
                    event.set()
                for process in processes:
                    if process.pid is None:
                        continue
                    process.join(2.0)
                    if process.is_alive():
                        process.terminate()
                        process.join(2.0)

    def test_windows_uia_exception_in_admission_releases_all_locks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_dir = Path(directory)
            slot_paths = tuple(
                lock_dir / f"bridge-slot-{index}.lock" for index in range(5)
            )
            with patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_LOCK_DIRECTORY",
                lock_dir,
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_PATH",
                lock_dir / "foreground.lock",
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_SLOT_PATHS",
                slot_paths,
            ):
                with self.assertRaises(ValueError):
                    with _windows_uia_bridge_admission("hotkey", "123"):
                        raise ValueError("simulated admission body error")

                # Verify all slots are available
                slot_descriptors = [_try_private_file_lock(p) for p in slot_paths]
                self.assertTrue(all(d is not None for d in slot_descriptors))
                for d in slot_descriptors:
                    _release_private_file_lock(d)

                # Verify window lock is available
                window_descriptor = _try_private_file_lock(
                    _windows_uia_window_lock_path("123")
                )
                self.assertIsNotNone(window_descriptor)
                _release_private_file_lock(window_descriptor)

                # Verify foreground lock is available
                fg_descriptor = _try_private_file_lock(
                    lock_dir / "foreground.lock"
                )
                self.assertIsNotNone(fg_descriptor)
                _release_private_file_lock(fg_descriptor)

                # Verify subsequent admission succeeds without issues
                with _windows_uia_bridge_admission("hotkey", "123"):
                    pass

    def test_windows_uia_admission_timeout_releases_all_acquired_locks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_dir = Path(directory)
            slot_paths = tuple(
                lock_dir / f"bridge-slot-{index}.lock" for index in range(5)
            )
            fg_lock_path = lock_dir / "foreground.lock"
            with patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_LOCK_DIRECTORY",
                lock_dir,
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_PATH",
                fg_lock_path,
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_SLOT_PATHS",
                slot_paths,
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS",
                0.05,
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS",
                0.01,
            ), patch(
                "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS",
                0.005,
            ):
                # Hold the foreground lock to force bridge admission for "hotkey" to time out
                held_fg = _try_private_file_lock(fg_lock_path)
                self.assertIsNotNone(held_fg)
                try:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "windows UIA bridge admission timed out",
                    ):
                        with _windows_uia_bridge_admission("hotkey", "123"):
                            self.fail("must not enter when foreground lock is held")
                finally:
                    _release_private_file_lock(held_fg)

                # All slot locks and window lock must be completely released
                for path in slot_paths:
                    d = _try_private_file_lock(path)
                    self.assertIsNotNone(d)
                    _release_private_file_lock(d)

                w = _try_private_file_lock(_windows_uia_window_lock_path("123"))
                self.assertIsNotNone(w)
                _release_private_file_lock(w)

    def test_windows_uia_private_locks_reject_unsafe_directory_and_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            unsafe_directory = root / "unsafe-directory"
            unsafe_directory.mkdir(mode=0o755)
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA lock directory is not private",
            ):
                _try_private_file_lock(unsafe_directory / "lock")

            wrong_mode = root / "wrong-mode.lock"
            wrong_mode.touch(mode=0o600)
            wrong_mode.chmod(0o644)
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA lock is not private",
            ):
                _try_private_file_lock(wrong_mode)

            symlink_target = root / "symlink-target.lock"
            symlink_target.touch(mode=0o600)
            symlink_path = root / "symlink.lock"
            symlink_path.symlink_to(symlink_target)
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA lock unavailable",
            ):
                _try_private_file_lock(symlink_path)

            hardlink_path = root / "hardlink.lock"
            os.link(symlink_target, hardlink_path)
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA lock is not private",
            ):
                _try_private_file_lock(symlink_target)

            fifo_path = root / "fifo.lock"
            os.mkfifo(fifo_path, 0o600)
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA lock is not private",
            ):
                _try_private_file_lock(fifo_path)

    def test_windows_uia_foreground_lock_excludes_another_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = str(Path(directory) / "foreground.lock")
            context = multiprocessing.get_context("fork")
            first_entered = context.Event()
            second_entered = context.Event()
            first_release = context.Event()
            second_release = context.Event()
            first = context.Process(
                target=_hold_windows_uia_lock,
                args=(lock_path, first_entered, first_release),
            )
            second = context.Process(
                target=_hold_windows_uia_lock,
                args=(lock_path, second_entered, second_release),
            )
            try:
                first.start()
                self.assertTrue(first_entered.wait(2.0))
                second.start()
                time.sleep(0.2)
                self.assertFalse(second_entered.is_set())
                first_release.set()
                self.assertTrue(second_entered.wait(2.0))
                second_release.set()
                first.join(2.0)
                second.join(2.0)
                self.assertEqual(first.exitcode, 0)
                self.assertEqual(second.exitcode, 0)
            finally:
                first_release.set()
                second_release.set()
                for process in (first, second):
                    if process.is_alive():
                        process.terminate()
                    process.join(2.0)

    def test_windows_uia_foreground_lock_times_out_then_can_be_reacquired(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = str(Path(directory) / "foreground.lock")
            context = multiprocessing.get_context("fork")
            entered = context.Event()
            release = context.Event()
            holder = context.Process(
                target=_hold_windows_uia_lock,
                args=(lock_path, entered, release),
            )
            try:
                holder.start()
                self.assertTrue(entered.wait(2.0))
                with patch(
                    "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_PATH",
                    Path(lock_path),
                ), patch(
                    "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_TIMEOUT_SECONDS",
                    0.05,
                ), patch(
                    "tools.agoda_portal_page_capture.WINDOWS_UIA_FOREGROUND_LOCK_POLL_SECONDS",
                    0.005,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "windows UIA foreground lock timed out",
                    ):
                        with _windows_uia_foreground_lock():
                            self.fail("contended lock must not be entered")
                    release.set()
                    holder.join(2.0)
                    self.assertEqual(holder.exitcode, 0)
                    with _windows_uia_foreground_lock():
                        pass
            finally:
                release.set()
                if holder.is_alive():
                    holder.terminate()
                holder.join(2.0)

    def test_windows_uia_subprocess_timeout_is_sanitized_after_admission_release(
        self,
    ) -> None:
        secret = "secret-card-text"
        timeout = subprocess.TimeoutExpired(
            ["bridge", secret],
            20,
            output=secret,
            stderr=secret,
        )
        exited: list[bool] = []

        class RecordingAdmission:
            def __enter__(self) -> float:
                return 3.0

            def __exit__(self, *_args: object) -> None:
                exited.append(True)

        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=RecordingAdmission(),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run",
            side_effect=timeout,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA browser command timed out",
            ) as raised:
                _run_windows_uia(
                    "computer",
                    "type-text",
                    "--window-id",
                    "1",
                    "--text",
                    secret,
                )

        self.assertEqual(exited, [True])
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(secret, rendered)

    def test_windows_uia_admission_releases_before_nonzero_return_error(
        self,
    ) -> None:
        exited: list[bool] = []

        class RecordingAdmission:
            def __enter__(self) -> float:
                return 4.0

            def __exit__(self, *_args: object) -> None:
                exited.append(True)

        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=RecordingAdmission(),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA browser command failed",
            ):
                _run_windows_uia(
                    "computer",
                    "press-key",
                    "--window-id",
                    "1",
                    "--key",
                    "Return",
                )

        self.assertEqual(exited, [True])

    def test_windows_uia_admission_releases_before_response_validation_errors(
        self,
    ) -> None:
        cases = (
            ("not-json", "windows UIA browser response was not JSON"),
            (json.dumps({"ok": False}), "windows UIA browser command failed"),
        )
        for stdout, expected in cases:
            with self.subTest(expected=expected):
                exited: list[bool] = []

                class RecordingAdmission:
                    def __enter__(self) -> float:
                        return 5.0

                    def __exit__(self, *_args: object) -> None:
                        exited.append(True)

                with patch(
                    "tools.agoda_portal_page_capture._windows_uia_script_path",
                    return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
                ), patch(
                    "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
                    return_value=RecordingAdmission(),
                ), patch(
                    "tools.agoda_portal_page_capture.subprocess.run"
                ) as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = stdout
                    with self.assertRaisesRegex(RuntimeError, expected):
                        _run_windows_uia(
                            "computer",
                            "get-app-state",
                            "--window-id",
                            "1",
                        )

                self.assertEqual(exited, [True])

    def test_windows_uia_state_adapter_uses_pinned_window(self) -> None:
        response = {
            "ok": True,
            "result": {"snapshot": {"treeText": "0 기본 Completed"}},
        }
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\\bridge\\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response)
            result = _run_windows_uia(
                "computer",
                "get-app-state",
                "--app",
                "msedge",
                "--window-id",
                "67514",
                "--restore-window",
            )

        self.assertEqual(result, response)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-Operation") + 1], "state")
        self.assertEqual(command[command.index("-WindowId") + 1], "67514")
        self.assertNotIn("msedge", command)

    def test_windows_uia_click_adapter_forwards_fresh_element_index(self) -> None:
        response = {"ok": True, "result": {"action": "click"}}
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\\bridge\\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response)
            _run_windows_uia(
                "computer",
                "click",
                "--app",
                "msedge",
                "--window-id",
                "67514",
                "--element-index",
                "812",
                "--expected-name-sha256",
                "f" * 64,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-Operation") + 1], "click")
        self.assertEqual(command[command.index("-ElementIndex") + 1], "812")
        self.assertEqual(
            command[command.index("-ExpectedNameSha256") + 1],
            "f" * 64,
        )

    def test_semantic_click_hashes_fresh_accessible_name(self) -> None:
        tree = "42 단추 Manage booking 1700000000"
        expected_name = "Manage booking 1700000000"
        self.assertEqual(_element_name(tree, 42), expected_name)
        with patch.dict(
            os.environ, {"AGODA_UI_BACKEND": "windows_uia"}
        ), patch(
            "tools.agoda_portal_page_capture._run_orca"
        ) as run_orca:
            _click(
                "msedge",
                67514,
                42,
                expected_name=expected_name,
            )

        arguments = run_orca.call_args.args
        expected_hash = hashlib.sha256(expected_name.encode()).hexdigest()
        self.assertEqual(
            arguments[arguments.index("--expected-name-sha256") + 1],
            expected_hash,
        )

    def test_windows_uia_select_adapter_requires_select_action(self) -> None:
        response = {"ok": True, "result": {"action": "select"}}
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\\bridge\\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response)
            _run_windows_uia(
                "computer",
                "perform-secondary-action",
                "--app",
                "msedge",
                "--window-id",
                "67514",
                "--element-index",
                "144",
                "--action",
                "Select",
            )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-Operation") + 1], "select")
        self.assertEqual(command[command.index("-ElementIndex") + 1], "144")

        with self.assertRaisesRegex(RuntimeError, "action unsupported"):
            _run_windows_uia(
                "computer",
                "perform-secondary-action",
                "--window-id",
                "67514",
                "--element-index",
                "144",
                "--action",
                "Expand",
            )

    def test_windows_uia_adapter_rejects_unsupported_command(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unsupported"):
            _run_windows_uia(
                "computer",
                "scroll",
                "--window-id",
                "67514",
            )

    def test_yearless_dates_are_resolved_by_weekday(self) -> None:
        january = DATE_RE.search("텍스트 Sun, Jan 25")
        december = DATE_RE.search("텍스트 Thu, Dec 25")
        self.assertIsNotNone(january)
        self.assertIsNotNone(december)
        self.assertEqual(_resolve_date(january).isoformat(), "2026-01-25")
        self.assertEqual(_resolve_date(december).isoformat(), "2025-12-25")

    def test_extracts_each_card_and_keeps_boundary_years_separate(self) -> None:
        tree = """
        100 그룹 mmb-booking-card--alpha
          101 제목 Example A
          102 텍스트 Check in
          103 텍스트 Sun, Jan 25
          104 텍스트 Check out
          105 텍스트 Mon, Jan 26
        200 그룹 mmb-booking-card--beta
          201 제목 Example B
          202 텍스트 Check in
          203 텍스트 Thu, Dec 25
          204 텍스트 Check out
          205 텍스트 Fri, Dec 26
        """
        cards = _extract_cards(tree, page_no=9)
        self.assertEqual(len(cards), 2)
        self.assertEqual([card["is_2026"] for card in cards], [1, 0])
        self.assertEqual(cards[0]["service_start_on"], "2026-01-25")
        self.assertEqual(cards[1]["service_start_on"], "2025-12-25")

    def test_page_buttons_ignore_booking_card_ids(self) -> None:
        tree = """
        0 기본 Completed
        810 단추 1
        812 단추 10
        814 단추 13
        816 단추 1701212145
        """
        self.assertEqual(_page_buttons(tree), {1: 810, 10: 812, 13: 814})

    def test_special_buttons_accept_agoda_label_variants(self) -> None:
        tree = """
        810 단추 Next
        812 단추 Previous page
        """
        self.assertEqual(
            _special_buttons(tree),
            {"Next page": 810, "Previous page": 812},
        )

    def test_hidden_middle_page_uses_next_range_control(self) -> None:
        tree = """
        0 기본 Completed
        810 단추 1
        812 단추 2
        814 단추 3
        816 단추 4
        818 단추 5
        820 단추 Next page
        822 단추 13
        """
        tree_after = """
        0 기본 Completed
        808 단추 1
        810 단추 6
        812 단추 7
        814 단추 8
        816 단추 9
        818 단추 10
        820 단추 11
        822 단추 12
        824 단추 Previous page
        826 단추 13
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            side_effect=[tree, tree, tree, tree_after, tree_after, tree_after],
        ), patch("tools.agoda_portal_page_capture._click") as click, patch(
            "tools.agoda_portal_page_capture._wait_page_controls",
            return_value=tree_after,
        ) as wait_controls, patch(
            "tools.agoda_portal_page_capture._wait_loaded",
            return_value=tree_after,
        ):
            result = _go_to_page("msedge", 1, 10)
        self.assertEqual(result, tree_after)
        self.assertEqual(click.call_args_list[0].args, ("msedge", 1, 820))
        self.assertEqual(click.call_args_list[1].args, ("msedge", 1, 818))
        wait_controls.assert_called_once()

    def test_page_tree_stabilizes_before_using_element_indexes(self) -> None:
        tree = """
        0 기본 Completed
        810 단추 1
        812 단추 2
        814 단추 13
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            side_effect=[tree, tree],
        ), patch("tools.agoda_portal_page_capture.time.sleep"):
            result = _wait_stable_page_tree("msedge", 1)
        self.assertEqual(result, tree)

    def test_loaded_page_waits_for_two_identical_card_observations(self) -> None:
        old_tree = """
        100 그룹 mmb-booking-card--old
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        """
        new_tree = """
        100 그룹 mmb-booking-card--new
          101 텍스트 Check in
          102 텍스트 Mon, Jan 26
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            side_effect=[old_tree, new_tree, new_tree],
        ), patch("tools.agoda_portal_page_capture.time.sleep"):
            result = _wait_loaded(
                "msedge",
                1,
                previous_card_hash=_card_block_hash(old_tree),
            )
        self.assertEqual(result, new_tree)

    def test_page_tree_waits_for_special_button_index_stability(self) -> None:
        first = """
        0 기본 Completed
        810 단추 1
        812 단추 2
        814 단추 13
        816 단추 Next page
        """
        second = """
        0 기본 Completed
        810 단추 1
        812 단추 2
        814 단추 13
        818 단추 Next page
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            side_effect=[first, second, second],
        ), patch("tools.agoda_portal_page_capture.time.sleep"):
            result = _wait_stable_page_tree("msedge", 1)
        self.assertEqual(result, second)

    def test_range_transition_retries_after_stale_click(self) -> None:
        initial = """
        0 기본 Completed
        810 단추 1
        812 단추 2
        814 단추 3
        816 단추 4
        818 단추 5
        820 단추 Next page
        822 단추 13
        """
        after_range = """
        0 기본 Completed
        808 단추 1
        810 단추 6
        812 단추 7
        814 단추 8
        816 단추 9
        818 단추 10
        820 단추 11
        822 단추 12
        824 단추 Previous page
        826 단추 13
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            side_effect=[initial, initial, initial, initial, initial, after_range, after_range],
        ), patch("tools.agoda_portal_page_capture._click") as click, patch(
            "tools.agoda_portal_page_capture._wait_page_controls",
            side_effect=[RuntimeError("stale click"), after_range],
        ), patch(
            "tools.agoda_portal_page_capture._wait_loaded",
            return_value=after_range,
        ):
            result = _go_to_page("msedge", 1, 10)
        self.assertEqual(result, after_range)
        self.assertEqual(
            [call.args for call in click.call_args_list],
            [("msedge", 1, 820), ("msedge", 1, 820), ("msedge", 1, 818)],
        )

    def test_page_range_wait_ignores_partial_and_requires_stability(self) -> None:
        partial = """
        0 기본 Completed
        810 단추 1
        """
        valid = """
        0 기본 Completed
        810 단추 1
        812 단추 4
        814 단추 5
        816 단추 6
        818 단추 7
        820 단추 8
        822 단추 13
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            side_effect=[partial, valid, valid],
        ), patch("tools.agoda_portal_page_capture.time.sleep"):
            result = _wait_page_controls(
                "msedge",
                1,
                [1, 2, 3, 4, 5, 13],
            )
        self.assertEqual(result, valid)

    def test_page_range_wait_accepts_card_progress_without_range_change(self) -> None:
        progressed = """
        0 기본 Completed
        810 단추 1
        812 단추 2
        814 단추 3
        816 단추 4
        818 단추 5
        820 단추 Next page
        822 단추 13
        100 그룹 mmb-booking-card--next-page
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        """
        with patch(
            "tools.agoda_portal_page_capture._tree",
            return_value=progressed,
        ), patch("tools.agoda_portal_page_capture.time.sleep"):
            result = _wait_page_controls(
                "msedge",
                1,
                [1, 2, 3, 4, 5, 13],
                previous_card_hash="old-card-page",
            )
        self.assertEqual(result, progressed)

    def test_non_service_date_does_not_promote_a_card(self) -> None:
        tree = """
        100 그룹 mmb-booking-card--gamma
          101 텍스트 Payment date
          102 텍스트 Sun, Jan 25
          103 텍스트 Check in
          104 텍스트 Thu, Dec 25
          105 텍스트 Check out
          106 텍스트 Fri, Dec 26
        """
        cards = _extract_cards(tree, page_no=9)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["is_2026"], 0)
        self.assertEqual(cards[0]["service_start_on"], "2025-12-25")

    def test_card_hash_ignores_pagination_after_last_card(self) -> None:
        card = """
        100 그룹 mmb-booking-card--hash-check
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        """
        self.assertEqual(
            _card_block_hash(card + "\n900 단추 Next page"),
            _card_block_hash(card + "\n901 텍스트 footer state changed"),
        )

    def test_duplicate_cards_are_retained_and_reported(self) -> None:
        duplicate_tree = """
        100 그룹 mmb-booking-card--same
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        200 그룹 mmb-booking-card--same
          201 텍스트 Check in
          202 텍스트 Mon, Jan 26
        """
        unique_template = """
        100 그룹 mmb-booking-card--{name}
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        """
        trees = [duplicate_tree] + [
            unique_template.format(name=f"unique-{page}")
            for page in EXPECTED_PAGE_ORDER[1:]
        ]
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "duplicates.sqlite"
            with patch(
                "tools.agoda_portal_page_capture._go_to_page",
                side_effect=trees,
            ):
                result = capture_pages(
                    app="msedge",
                    window_id=1,
                    pages=list(EXPECTED_PAGE_ORDER),
                    db_path=db_path,
                    run_id="duplicate-run",
                )
            self.assertEqual(result["page_summaries"][0]["duplicate_booking_id_count"], 1)
            self.assertEqual(result["total_cards"], 14)
            self.assertEqual(result["distinct_total_bookings"], 13)
            self.assertEqual(result["duplicate_total_rows"], 1)

    def test_capture_writes_staging_db_before_connection_closes(self) -> None:
        page_tree = """
        100 그룹 mmb-booking-card--delta
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
          103 텍스트 Check out
          104 텍스트 Mon, Jan 26
        """
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "staging.sqlite"
            trees = [
                page_tree.replace("delta", f"booking-{page_no}")
                for page_no in EXPECTED_PAGE_ORDER
            ]
            with patch(
                "tools.agoda_portal_page_capture._go_to_page",
                side_effect=trees,
            ):
                result = capture_pages(
                    app="msedge",
                    window_id=1,
                    pages=list(EXPECTED_PAGE_ORDER),
                    db_path=db_path,
                    run_id="test-run",
                )
            self.assertEqual(result["total_cards"], 13)
            self.assertEqual(result["distinct_target_year_bookings"], 13)
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM agoda_pages").fetchone()[0],
                    13,
                )

    def test_single_page_capture_publishes_isolated_page_db(self) -> None:
        page_tree = """
        100 그룹 mmb-booking-card--single-page
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
          103 텍스트 Check out
          104 텍스트 Mon, Jan 26
        """
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "page-10.sqlite"
            with patch(
                "tools.agoda_portal_page_capture._go_to_page",
                return_value=page_tree,
            ):
                result = capture_page(
                    app="msedge",
                    window_id=1,
                    page_no=10,
                    db_path=db_path,
                    run_id="page-10-run",
                )
            self.assertEqual(result["captured_pages"], [10])
            self.assertEqual(result["total_cards"], 1)
            with sqlite3.connect(
                f"file:{db_path}?mode=ro&immutable=1",
                uri=True,
            ) as connection:
                self.assertEqual(
                    connection.execute("SELECT page_no FROM agoda_pages").fetchone()[0],
                    10,
                )

    def test_single_page_capture_can_use_already_stable_current_page(self) -> None:
        page_tree = """
        0 기본 Completed
        810 단추 1
        812 단추 9
        814 단추 10
        816 단추 11
        818 단추 13
        100 그룹 mmb-booking-card--current-page
          101 텍스트 Check in
          102 텍스트 Sun, Jan 25
        """
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "page-10-current.sqlite"
            with patch(
                "tools.agoda_portal_page_capture._wait_stable_page_tree",
                return_value=page_tree,
            ), patch(
                "tools.agoda_portal_page_capture._go_to_page",
                side_effect=AssertionError("must not navigate an already current page"),
            ):
                result = capture_page(
                    app="msedge",
                    window_id=1,
                    page_no=10,
                    db_path=db_path,
                    run_id="page-10-current-run",
                    assume_current=True,
                )
            self.assertEqual(result["captured_pages"], [10])
            self.assertEqual(result["total_cards"], 1)

    def test_partial_page_capture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                capture_pages(
                    app="msedge",
                    window_id=1,
                    pages=[10, 9],
                    db_path=Path(directory) / "partial.sqlite",
                    run_id="partial-run",
                )

    def test_non_tmp_staging_path_is_rejected(self) -> None:
        outside = Path("/var/tmp") / "agoda-not-private.sqlite"
        with self.assertRaises(RuntimeError):
            capture_pages(
                app="msedge",
                window_id=1,
                pages=list(EXPECTED_PAGE_ORDER),
                db_path=outside,
                run_id="non-private-run",
            )

    def test_windows_uia_admission_succeeds_past_old_thirty_second_boundary_before_queue_boundary(
        self,
    ) -> None:
        with patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1000.0, 1045.0, 1045.0, 1045.0],
        ), patch(
            "tools.agoda_portal_page_capture._try_windows_uia_bridge_slot",
            side_effect=[None, 12],
        ), patch(
            "tools.agoda_portal_page_capture._bounded_lock_sleep",
            return_value=True,
        ) as mock_sleep, patch(
            "tools.agoda_portal_page_capture._release_private_file_lock"
        ) as mock_release:
            with _windows_uia_bridge_admission("state", "1") as remaining:
                self.assertEqual(remaining, 60.0)

        self.assertEqual(mock_sleep.call_count, 1)
        admission_deadline_arg = mock_sleep.call_args.args[0]
        self.assertAlmostEqual(admission_deadline_arg, 1240.0)
        mock_release.assert_called_once_with(12)

    def test_windows_uia_subprocess_timeout_is_capped_at_process_cap_despite_larger_budget(
        self,
    ) -> None:
        response = {"ok": True, "result": {"snapshot": {"treeText": ""}}}
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(240.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response)
            _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        self.assertEqual(
            run.call_args.kwargs["timeout"],
            WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS,
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 60.0)

    def test_windows_uia_budget_not_exceeding_process_reserve_fails_before_subprocess_spawn(
        self,
    ) -> None:
        for budget in (60.0, 50.0, 0.0, -10.0):
            with self.subTest(budget=budget):
                with patch(
                    "tools.agoda_portal_page_capture._windows_uia_script_path",
                    return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
                ), patch(
                    "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS",
                    budget,
                ), patch(
                    "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS",
                    60.0,
                ), patch(
                    "tools.agoda_portal_page_capture.subprocess.run"
                ) as run:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "windows UIA bridge admission timed out",
                    ):
                        _run_windows_uia(
                            "computer", "get-app-state", "--window-id", "1"
                        )
                    run.assert_not_called()

    def test_windows_uia_admission_fails_immediately_when_no_queue_window(
        self,
    ) -> None:
        with patch(
            "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_TOTAL_TIMEOUT_SECONDS",
            60.0,
        ), patch(
            "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS",
            60.0,
        ), patch(
            "tools.agoda_portal_page_capture._try_windows_uia_bridge_slot"
        ) as mock_slot:
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge admission timed out",
            ):
                with _windows_uia_bridge_admission("state", "1"):
                    pass
            mock_slot.assert_not_called()

    def test_windows_uia_slot_acquired_after_admission_boundary_is_released_without_spawn(
        self,
    ) -> None:
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1000.0, 1000.0, 1241.0, 1241.0],
        ), patch(
            "tools.agoda_portal_page_capture._try_windows_uia_bridge_slot",
            return_value=12,
        ), patch(
            "tools.agoda_portal_page_capture._release_private_file_lock"
        ) as mock_release, patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge admission timed out",
            ):
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        mock_run.assert_not_called()
        mock_release.assert_called_once_with(12)

    def test_windows_uia_nonpositive_process_cap_fails_immediately(
        self,
    ) -> None:
        for process_cap in (0.0, -1.0, -60.0):
            with self.subTest(process_cap=process_cap):
                with patch(
                    "tools.agoda_portal_page_capture._windows_uia_script_path",
                    return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
                ), patch(
                    "tools.agoda_portal_page_capture.WINDOWS_UIA_BRIDGE_PROCESS_TIMEOUT_SECONDS",
                    process_cap,
                ), patch(
                    "tools.agoda_portal_page_capture._try_windows_uia_bridge_slot"
                ) as mock_slot, patch(
                    "tools.agoda_portal_page_capture.subprocess.run"
                ) as mock_run:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "windows UIA bridge admission timed out",
                    ):
                        _run_windows_uia(
                            "computer", "get-app-state", "--window-id", "1"
                        )
                    mock_slot.assert_not_called()
                    mock_run.assert_not_called()

                    with self.assertRaisesRegex(
                        RuntimeError,
                        "windows UIA bridge admission timed out",
                    ):
                        with _windows_uia_bridge_admission("state", "1"):
                            pass
                    mock_slot.assert_not_called()

    def test_windows_uia_malformed_json_response_does_not_chain_raw_document(
        self,
    ) -> None:
        secret_token = "SECRET_TOKEN_BOOKING_99999"
        secret_url = "https://internal.agoda.com/sensitive_url_path"
        malformed_body = f'{{"booking": "{secret_token}", "url": "{secret_url}", invalid_json_here'
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = malformed_body
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA browser response was not JSON",
            ) as raised:
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(secret_token, rendered)
        self.assertNotIn(secret_url, rendered)
        self.assertNotIn("JSONDecodeError", rendered)
        self.assertNotIn(malformed_body, rendered)

    def test_windows_uia_nonzero_bridge_exit_sanitizes_stdout_and_stderr(
        self,
    ) -> None:
        secret_stdout = "SECRET_STDOUT_LEAK_12345"
        secret_stderr = "SECRET_STDERR_LEAK_67890"
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 1
            run.return_value.stdout = secret_stdout
            run.return_value.stderr = secret_stderr
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA browser command failed",
            ) as raised:
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(secret_stdout, rendered)
        self.assertNotIn(secret_stderr, rendered)

    def test_windows_uia_not_ok_response_does_not_leak_error_payload(
        self,
    ) -> None:
        secret_code = "SECRET_ERROR_CODE_9999"
        secret_detail = "SECRET_ERROR_DETAIL_8888"
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(
                {"ok": False, "error": {"code": secret_code, "detail": secret_detail}}
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA browser command failed",
            ) as raised:
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(secret_code, rendered)
        self.assertNotIn(secret_detail, rendered)

    def test_windows_uia_script_path_failure_does_not_chain_process_error_or_output(
        self,
    ) -> None:
        secret_stdout = "SECRET_WSLPATH_STDOUT_LEAK_111"
        secret_stderr = "SECRET_WSLPATH_STDERR_LEAK_222"
        page_capture._windows_uia_script_path.cache_clear()
        try:
            with patch(
                "tools.agoda_portal_page_capture.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    returncode=1,
                    cmd=["wslpath", "-w", "agoda_windows_uia_bridge.ps1"],
                    output=secret_stdout,
                    stderr=secret_stderr,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "windows UIA bridge path resolution failed",
                ) as raised:
                    page_capture._windows_uia_script_path(timeout=10.0)

            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
            rendered = "".join(
                traceback.format_exception(
                    type(raised.exception),
                    raised.exception,
                    raised.exception.__traceback__,
                )
            )
            self.assertNotIn(secret_stdout, rendered)
            self.assertNotIn(secret_stderr, rendered)
            self.assertNotIn("CalledProcessError", rendered)
        finally:
            page_capture._windows_uia_script_path.cache_clear()

    def test_windows_uia_script_path_timeout_does_not_chain_timeout_error_or_output(
        self,
    ) -> None:
        secret_stdout = "SECRET_WSLPATH_TIMEOUT_OUTPUT_333"
        secret_stderr = "SECRET_WSLPATH_TIMEOUT_STDERR_444"
        page_capture._windows_uia_script_path.cache_clear()
        try:
            with patch(
                "tools.agoda_portal_page_capture.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["wslpath", "-w", "agoda_windows_uia_bridge.ps1"],
                    timeout=10.0,
                    output=secret_stdout,
                    stderr=secret_stderr,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "windows UIA bridge path resolution timed out",
                ) as raised:
                    page_capture._windows_uia_script_path(timeout=10.0)

            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
            rendered = "".join(
                traceback.format_exception(
                    type(raised.exception),
                    raised.exception,
                    raised.exception.__traceback__,
                )
            )
            self.assertNotIn(secret_stdout, rendered)
            self.assertNotIn(secret_stderr, rendered)
            self.assertNotIn("TimeoutExpired", rendered)
        finally:
            page_capture._windows_uia_script_path.cache_clear()

    def test_windows_uia_script_path_empty_stdout_fails_without_cause_or_context(
        self,
    ) -> None:
        page_capture._windows_uia_script_path.cache_clear()
        try:
            with patch(
                "tools.agoda_portal_page_capture.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["wslpath", "-w", "dummy"],
                    returncode=0,
                    stdout="   \n",
                    stderr="",
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "windows UIA bridge path resolution failed",
                ) as raised:
                    page_capture._windows_uia_script_path(timeout=10.0)

            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
        finally:
            page_capture._windows_uia_script_path.cache_clear()

    def test_orca_malformed_json_response_does_not_chain_raw_document(
        self,
    ) -> None:
        secret_token = "SECRET_ORCA_RAW_DOC_555"
        malformed_body = f'{{"status": "{secret_token}", invalid_json'
        with patch.dict(os.environ, {"AGODA_UI_BACKEND": ""}, clear=False), patch(
            "tools.agoda_portal_page_capture.subprocess.Popen"
        ) as mock_popen:
            mock_process = mock_popen.return_value
            mock_process.communicate.return_value = (malformed_body, "")
            mock_process.returncode = 0
            with self.assertRaisesRegex(
                RuntimeError,
                "browser response was not JSON",
            ) as raised:
                page_capture._run_orca("get-app-state")

        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn(secret_token, rendered)
        self.assertNotIn("JSONDecodeError", rendered)
        self.assertNotIn(malformed_body, rendered)

    def test_windows_uia_powershell_catch_allowlists_and_sanitizes_errors(
        self,
    ) -> None:
        script_path = Path(__file__).resolve().parents[2] / "tools" / "agoda_windows_uia_bridge.ps1"
        self.assertTrue(script_path.is_file())
        script_content = script_path.read_text(encoding="utf-8")
        expected_allowlist = [
            "window_not_found",
            "browser_omnibox_missing_or_ambiguous",
            "browser_content_root_missing_or_ambiguous",
            "semantic_action_target_missing_or_ambiguous",
            "element_not_found",
            "element_not_selectable",
            "window_not_focused",
            "browser_omnibox_not_focused",
            "unsupported_hotkey",
            "unsupported_key",
            "focused_value_receiver_missing",
        ]
        for code in expected_allowlist:
            self.assertIn(f"'{code}'", script_content)
        self.assertIn("'bridge_execution_failed'", script_content)

    def test_windows_uia_path_resolution_consumes_total_deadline(
        self,
    ) -> None:
        response = {"ok": True, "result": {"snapshot": {"treeText": ""}}}
        passed_deadlines: list[float | None] = []

        @contextlib.contextmanager
        def recording_admission(operation: str, window_id: str, *, total_deadline: float | None = None):
            passed_deadlines.append(total_deadline)
            yield 60.0

        with patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1050.0, 1050.0, 1050.0, 1050.0],
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ) as mock_script_path, patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            side_effect=recording_admission,
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(response)
            _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        self.assertEqual(passed_deadlines, [1300.0])
        mock_script_path.assert_called_once_with(timeout=10.0)

    def test_windows_uia_path_resolution_expiry_fails_before_admission_or_spawn(
        self,
    ) -> None:
        with patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1250.0, 1250.0],
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission"
        ) as mock_admission, patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge admission timed out",
            ):
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        mock_admission.assert_not_called()
        mock_run.assert_not_called()

    def test_windows_uia_pre_spawn_recomputes_remaining_and_caps_subprocess_timeout(
        self,
    ) -> None:
        response = {"ok": True, "result": {"snapshot": {"treeText": ""}}}
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1000.0, 1255.0, 1255.0],
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(response)
            _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        self.assertEqual(mock_run.call_args.kwargs["timeout"], 45.0)

    def test_windows_uia_pre_spawn_expiry_fails_without_spawn(
        self,
    ) -> None:
        with patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ), patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1000.0, 1301.0, 1301.0],
        ), patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge admission timed out",
            ):
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")

        mock_run.assert_not_called()


class AgodaPortalDetailFairnessTests(unittest.TestCase):
    RUN_ID = "fairness-run"

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(
            """
            CREATE TABLE capture_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                booking_id_sha256 TEXT NOT NULL,
                tab_name TEXT NOT NULL,
                page_no INTEGER NOT NULL,
                card_position INTEGER NOT NULL,
                attempt_no INTEGER NOT NULL,
                started_at_utc TEXT NOT NULL,
                finished_at_utc TEXT,
                capture_status TEXT NOT NULL,
                failure_code TEXT
            );
            CREATE TABLE booking_detail_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                booking_id_sha256 TEXT NOT NULL
            );
            """
        )

    def tearDown(self) -> None:
        self.connection.close()

    @staticmethod
    def _target(
        booking_hash: str,
        card_position: int,
        *,
        page_no: int = 1,
        tab_name: str = "Completed",
    ) -> detail_capture.SourceBooking:
        return detail_capture.SourceBooking(
            page_no=page_no,
            booking_id=f"booking-{booking_hash}",
            booking_id_sha256=booking_hash,
            service_start_on="2026-01-01",
            service_end_on="2026-01-02",
            reservation_status="Completed",
            list_card_sha256=f"card-{booking_hash}",
            tab_name=tab_name,
            card_position=card_position,
        )

    @staticmethod
    def _snapshot(
        *bookings: detail_capture.SourceBooking,
    ) -> detail_capture.SourceSnapshot:
        return detail_capture.SourceSnapshot(
            path=Path("/tmp/fairness-source.sqlite"),
            file_sha256="source-file",
            source_run_id="source-run",
            source_capture_set_sha256="capture-set",
            membership_ordered_sha256="ordered",
            membership_set_sha256="set",
            bookings=tuple(bookings),
            page_manifest={},
        )

    def _add_attempt(self, booking_hash: str, attempt_no: int, status: str) -> None:
        self.connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, capture_status
            ) VALUES (?, ?, 'Completed', 1, 1, ?, '2026-08-16T00:00:00Z', ?)
            """,
            (self.RUN_ID, booking_hash, attempt_no, status),
        )
        self.connection.commit()

    def test_fairness_prefers_zero_failures_over_sixteen_failures(self) -> None:
        hard = self._target("hard", 1)
        unseen = self._target("unseen", 2)
        for attempt_no in range(1, 17):
            self._add_attempt("hard", attempt_no, "failed_parse")

        ordered = detail_capture._ordered_unresolved_targets(
            self.connection, self.RUN_ID, (hard, unseen)
        )

        self.assertEqual(
            [target.booking_id_sha256 for target in ordered],
            ["unseen", "hard"],
        )

    def test_fairness_ties_use_card_position_then_booking_hash(self) -> None:
        targets = (
            self._target("z", 2),
            self._target("b", 1),
            self._target("a", 1),
        )
        for booking_hash in ("z", "b", "a"):
            self._add_attempt(booking_hash, 1, "failed_load")

        ordered = detail_capture._ordered_unresolved_targets(
            self.connection, self.RUN_ID, targets
        )

        self.assertEqual(
            [target.booking_id_sha256 for target in ordered],
            ["a", "b", "z"],
        )

    def test_fairness_excludes_existing_success_snapshot(self) -> None:
        done = self._target("done", 1)
        pending = self._target("pending", 2)
        self.connection.execute(
            "INSERT INTO booking_detail_snapshots(run_id, booking_id_sha256) "
            "VALUES (?, ?)",
            (self.RUN_ID, "done"),
        )
        self.connection.commit()

        ordered = detail_capture._ordered_unresolved_targets(
            self.connection, self.RUN_ID, (done, pending)
        )

        self.assertEqual(
            [target.booking_id_sha256 for target in ordered],
            ["pending"],
        )

    def test_fairness_ignores_started_and_success_attempts(self) -> None:
        nonfailed = self._target("nonfailed", 2)
        failed = self._target("failed", 1)
        self._add_attempt("nonfailed", 1, "started")
        self._add_attempt("nonfailed", 2, "success")
        self._add_attempt("failed", 1, "failed_verify")

        ordered = detail_capture._ordered_unresolved_targets(
            self.connection, self.RUN_ID, (failed, nonfailed)
        )

        self.assertEqual(
            [target.booking_id_sha256 for target in ordered],
            ["nonfailed", "failed"],
        )

    def test_close_interrupted_attempts_is_idempotent(self) -> None:
        self._add_attempt("current", 1, "started")
        self.connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, capture_status
            ) VALUES ('other-run', 'other', 'Completed', 1, 1, 1,
                      '2026-08-16T00:00:00Z', 'started')
            """
        )
        self.connection.commit()

        self.assertEqual(
            detail_capture._close_interrupted_attempts(
                self.connection, self.RUN_ID
            ),
            1,
        )
        self.assertEqual(
            detail_capture._close_interrupted_attempts(
                self.connection, self.RUN_ID
            ),
            0,
        )
        current = self.connection.execute(
            "SELECT capture_status, failure_code, finished_at_utc "
            "FROM capture_attempts WHERE run_id=?",
            (self.RUN_ID,),
        ).fetchone()
        other_status = self.connection.execute(
            "SELECT capture_status FROM capture_attempts WHERE run_id='other-run'"
        ).fetchone()[0]
        self.assertEqual(
            current[0:2],
            ("failed_load", "interrupted_previous_process"),
        )
        self.assertIsNotNone(current[2])
        self.assertEqual(other_status, "started")

    def test_page_fairness_prefers_later_unseen_page_over_early_hard_page(
        self,
    ) -> None:
        hard = self._target("hard-page", 1, page_no=1)
        unseen = self._target("unseen-page", 1, page_no=2)
        for attempt_no in range(1, 17):
            self._add_attempt("hard-page", attempt_no, "failed_parse")

        batches = detail_capture._ordered_unresolved_page_batches(
            self.connection,
            self.RUN_ID,
            self._snapshot(hard, unseen),
        )

        self.assertEqual([batch.page_no for batch in batches], [2, 1])
        self.assertEqual(
            [batch.page_target_count for batch in batches],
            [1, 1],
        )

    def test_page_fairness_ties_keep_canonical_tab_and_page_order(self) -> None:
        completed_two = self._target("completed-two", 1, page_no=2)
        cancelled_one = self._target(
            "cancelled-one", 1, page_no=1, tab_name="Cancelled"
        )
        completed_one = self._target("completed-one", 1, page_no=1)

        batches = detail_capture._ordered_unresolved_page_batches(
            self.connection,
            self.RUN_ID,
            self._snapshot(completed_two, cancelled_one, completed_one),
        )

        self.assertEqual(
            [(batch.tab_name, batch.page_no) for batch in batches],
            [("Completed", 1), ("Completed", 2), ("Cancelled", 1)],
        )

    def test_page_fairness_omits_success_only_page(self) -> None:
        done = self._target("done-page", 1, page_no=1)
        pending = self._target("pending-page", 1, page_no=2)
        self.connection.execute(
            "INSERT INTO booking_detail_snapshots(run_id, booking_id_sha256) "
            "VALUES (?, ?)",
            (self.RUN_ID, "done-page"),
        )
        self.connection.commit()

        batches = detail_capture._ordered_unresolved_page_batches(
            self.connection,
            self.RUN_ID,
            self._snapshot(done, pending),
        )

        self.assertEqual([batch.page_no for batch in batches], [2])
        self.assertEqual(batches[0].page_target_count, 1)

    def test_page_fairness_ignores_started_and_success_attempts(self) -> None:
        nonfailed = self._target("nonfailed-page", 1, page_no=1)
        failed = self._target("failed-page", 1, page_no=2)
        self._add_attempt("nonfailed-page", 1, "started")
        self._add_attempt("nonfailed-page", 2, "success")
        self._add_attempt("failed-page", 1, "failed_load")

        batches = detail_capture._ordered_unresolved_page_batches(
            self.connection,
            self.RUN_ID,
            self._snapshot(failed, nonfailed),
        )

        self.assertEqual([batch.page_no for batch in batches], [1, 2])

    def test_fairness_empty_input_returns_empty_tuple(self) -> None:
        self.assertEqual(
            detail_capture._ordered_unresolved_targets(
                self.connection, self.RUN_ID, ()
            ),
            (),
        )


class AgodaWindowsUiaCSharpBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        page_capture._compiled_csharp_bridge = None

    def tearDown(self) -> None:
        page_capture._compiled_csharp_bridge = None

    def test_default_csharp_selection_when_env_not_powershell(self) -> None:
        response = {
            "ok": True,
            "result": {"snapshot": {"treeText": "0 기본 Completed"}},
        }
        mock_exe_info = {
            "win_path": r"C:\Users\tester\AppData\Local\Temp\agoda_uia_123.exe",
            "wsl_path": "/tmp/agoda_uia_123.exe",
            "sha256": "fake_sha256_hash",
        }
        for env_val in ("", "csharp", "c#"):
            with self.subTest(env_val=env_val):
                with patch.dict(os.environ, {"AGODA_WINDOWS_UIA_IMPLEMENTATION": env_val}, clear=False), patch(
                    "tools.agoda_portal_page_capture._ensure_csharp_bridge",
                    return_value=mock_exe_info,
                ) as mock_ensure, patch(
                    "tools.agoda_portal_page_capture._verify_csharp_bridge_executable"
                ) as mock_verify, patch(
                    "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
                    return_value=contextlib.nullcontext(60.0),
                ), patch(
                    "tools.agoda_portal_page_capture.subprocess.run"
                ) as mock_run:
                    mock_run.return_value.returncode = 0
                    mock_run.return_value.stdout = json.dumps(response)

                    res = _run_windows_uia("computer", "get-app-state", "--window-id", "101")
                    self.assertTrue(res["ok"])
                    mock_ensure.assert_called_once()
                    self.assertEqual(mock_verify.call_count, 2)
                    self.assertEqual(
                        mock_run.call_args[0][0],
                        ["/tmp/agoda_uia_123.exe", "-Operation", "state", "-WindowId", "101"],
                    )

    def test_explicit_powershell_override(self) -> None:
        response = {
            "ok": True,
            "result": {"snapshot": {"treeText": "0 기본 Completed"}},
        }
        with patch.dict(os.environ, {"AGODA_WINDOWS_UIA_IMPLEMENTATION": "powershell"}, clear=False), patch(
            "tools.agoda_portal_page_capture._windows_uia_script_path",
            return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
        ) as mock_ps_path, patch(
            "tools.agoda_portal_page_capture._ensure_csharp_bridge"
        ) as mock_csharp_ensure, patch(
            "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
            return_value=contextlib.nullcontext(60.0),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(response)

            res = _run_windows_uia("computer", "get-app-state", "--window-id", "101")
            self.assertTrue(res["ok"])
            mock_ps_path.assert_called_once()
            mock_csharp_ensure.assert_not_called()
            self.assertEqual(
                mock_run.call_args[0][0][:6],
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", r"C:\bridge\agoda_windows_uia_bridge.ps1"],
            )

    def test_random_path_and_csc_compilation_command_structure(self) -> None:
        fake_content = b"MZ_FAKE_DOTNET_EXECUTABLE_BINARY"
        expected_sha256 = hashlib.sha256(fake_content).hexdigest()

        with patch(
            "tools.agoda_portal_page_capture._resolve_csharp_source_windows_path",
            return_value=r"C:\repo\tools\AgodaWindowsUiaBridge.cs",
        ) as mock_src, patch(
            "tools.agoda_portal_page_capture._resolve_windows_temp_dir",
            return_value=(r"C:\Users\testuser\AppData\Local\Temp", "/tmp/wsl_temp"),
        ) as mock_temp, patch(
            "tools.agoda_portal_page_capture.secrets.token_hex",
            return_value="deadbeef0123456789abcdef00112233",
        ), patch(
            "tools.agoda_portal_page_capture.os.path.exists",
            return_value=False,
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_compile_run, patch(
            "tools.agoda_portal_page_capture.os.path.isfile",
            return_value=True,
        ), patch(
            "builtins.open",
            unittest.mock.mock_open(read_data=fake_content),
        ):
            mock_compile_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

            exe_info = _ensure_csharp_bridge(
                total_deadline=time.monotonic() + 300.0,
                process_cap=60.0,
            )

            mock_src.assert_called_once()
            mock_temp.assert_called_once()
            self.assertEqual(
                exe_info["win_path"],
                r"C:\Users\testuser\AppData\Local\Temp\agoda_uia_deadbeef0123456789abcdef00112233.exe",
            )
            self.assertEqual(
                exe_info["wsl_path"],
                "/tmp/wsl_temp/agoda_uia_deadbeef0123456789abcdef00112233.exe",
            )
            self.assertEqual(exe_info["sha256"], expected_sha256)

            cmd = mock_compile_run.call_args[0][0]
            self.assertEqual(cmd[0], CSC_PATH_DEFAULT)
            self.assertIn("/noconfig", cmd)
            self.assertIn("/platform:x64", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\mscorlib.dll", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\System.dll", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\System.Core.dll", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\WPF\\UIAutomationClient.dll", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\WPF\\UIAutomationTypes.dll", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\System.Windows.Forms.dll", cmd)
            self.assertIn(f"/r:{FRAMEWORK64_DIR_DEFAULT}\\System.Web.Extensions.dll", cmd)
            self.assertIn(f"/out:{exe_info['win_path']}", cmd)
            self.assertIn(r"C:\repo\tools\AgodaWindowsUiaBridge.cs", cmd)

    def test_one_compile_per_process(self) -> None:
        fake_content = b"BINARY_CONTENT"
        with patch(
            "tools.agoda_portal_page_capture._resolve_csharp_source_windows_path",
            return_value=r"C:\repo\tools\AgodaWindowsUiaBridge.cs",
        ), patch(
            "tools.agoda_portal_page_capture._resolve_windows_temp_dir",
            return_value=(r"C:\Temp", "/tmp/temp"),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_compile_run, patch(
            "tools.agoda_portal_page_capture.os.path.exists",
            return_value=False,
        ), patch(
            "tools.agoda_portal_page_capture.os.path.isfile",
            return_value=True,
        ), patch(
            "builtins.open",
            unittest.mock.mock_open(read_data=fake_content),
        ):
            mock_compile_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

            info1 = _ensure_csharp_bridge(
                total_deadline=time.monotonic() + 300.0,
                process_cap=60.0,
            )
            info2 = _ensure_csharp_bridge(
                total_deadline=time.monotonic() + 300.0,
                process_cap=60.0,
            )
            info3 = _ensure_csharp_bridge(
                total_deadline=time.monotonic() + 300.0,
                process_cap=60.0,
            )

            self.assertIs(info1, info2)
            self.assertIs(info2, info3)
            self.assertEqual(mock_compile_run.call_count, 1)

    def test_hash_mismatch_fails_closed_without_spawn(self) -> None:
        exe_info = {
            "win_path": r"C:\Temp\agoda_uia.exe",
            "wsl_path": "/tmp/agoda_uia.exe",
            "sha256": "correct_sha256_value",
        }
        with patch(
            "tools.agoda_portal_page_capture.os.path.isfile",
            return_value=True,
        ), patch(
            "builtins.open",
            unittest.mock.mock_open(read_data=b"tampered_or_corrupted_binary"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge executable verification failed",
            ) as raised:
                _verify_csharp_bridge_executable(exe_info)

            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        with patch.dict(os.environ, {"AGODA_WINDOWS_UIA_IMPLEMENTATION": ""}, clear=False), patch(
            "tools.agoda_portal_page_capture._ensure_csharp_bridge",
            return_value=exe_info,
        ), patch(
            "tools.agoda_portal_page_capture._verify_csharp_bridge_executable",
            side_effect=RuntimeError("windows UIA bridge executable verification failed"),
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge executable verification failed",
            ):
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")
            mock_run.assert_not_called()

    def test_missing_compiled_exe_fails_closed_without_spawn(self) -> None:
        exe_info = {
            "win_path": r"C:\Temp\missing.exe",
            "wsl_path": "/tmp/missing.exe",
            "sha256": "expected_sha",
        }
        with patch(
            "tools.agoda_portal_page_capture.os.path.isfile",
            return_value=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge executable verification failed",
            ) as raised:
                _verify_csharp_bridge_executable(exe_info)

            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_deadline_expiry_during_csharp_preparation(self) -> None:
        with patch(
            "tools.agoda_portal_page_capture.time.monotonic",
            side_effect=[1000.0, 1250.0],
        ), patch(
            "tools.agoda_portal_page_capture._ensure_csharp_bridge"
        ) as mock_ensure, patch(
            "tools.agoda_portal_page_capture.subprocess.run"
        ) as mock_run:
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge admission timed out",
            ):
                _run_windows_uia("computer", "get-app-state", "--window-id", "1")
            mock_ensure.assert_not_called()
            mock_run.assert_not_called()

        with patch(
            "tools.agoda_portal_page_capture.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="wslpath", timeout=10.0),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge path resolution timed out",
            ) as raised:
                _resolve_csharp_source_windows_path(timeout=10.0)
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        with patch(
            "tools.agoda_portal_page_capture.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="cmd.exe", timeout=10.0),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge path resolution timed out",
            ) as raised:
                _resolve_windows_temp_dir(timeout=10.0)
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        with patch(
            "tools.agoda_portal_page_capture._resolve_csharp_source_windows_path",
            return_value=r"C:\AgodaWindowsUiaBridge.cs",
        ), patch(
            "tools.agoda_portal_page_capture._resolve_windows_temp_dir",
            return_value=(r"C:\Temp", "/tmp/temp"),
        ), patch(
            "tools.agoda_portal_page_capture.os.path.exists",
            return_value=False,
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="csc.exe", timeout=30.0),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge compilation timed out",
            ) as raised:
                _ensure_csharp_bridge(
                    total_deadline=time.monotonic() + 300.0,
                    process_cap=60.0,
                )
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        with patch(
            "tools.agoda_portal_page_capture._resolve_csharp_source_windows_path",
            return_value=r"C:\AgodaWindowsUiaBridge.cs",
        ), patch(
            "tools.agoda_portal_page_capture._resolve_windows_temp_dir",
            return_value=(r"C:\Temp", "/tmp/temp"),
        ), patch(
            "tools.agoda_portal_page_capture.os.path.exists",
            return_value=False,
        ), patch(
            "tools.agoda_portal_page_capture.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="err", stderr="err"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "windows UIA bridge compilation failed",
            ) as raised:
                _ensure_csharp_bridge(
                    total_deadline=time.monotonic() + 300.0,
                    process_cap=60.0,
                )
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_csharp_bridge_atexit_cleanup(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        self.assertTrue(os.path.exists(temp_path))
        page_capture._compiled_csharp_bridge = {
            "win_path": r"C:\Temp\test.exe",
            "wsl_path": temp_path,
            "sha256": "fake",
        }
        _cleanup_compiled_bridge()
        self.assertFalse(os.path.exists(temp_path))

        _cleanup_compiled_bridge()

    def test_command_parity_across_all_six_operations(self) -> None:
        operations_data = [
            ("get-app-state", ["computer", "get-app-state", "--window-id", "10"], ["-Operation", "state", "-WindowId", "10"]),
            ("click", ["computer", "click", "--window-id", "10", "--element-index", "5", "--expected-name-sha256", "abc"], ["-Operation", "click", "-WindowId", "10", "-ExpectedNameSha256", "abc", "-ElementIndex", "5"]),
            ("select", ["computer", "perform-secondary-action", "--window-id", "10", "--element-index", "3", "--action", "select", "--expected-name-sha256", "def"], ["-Operation", "select", "-WindowId", "10", "-ExpectedNameSha256", "def", "-ElementIndex", "3"]),
            ("hotkey", ["computer", "hotkey", "--window-id", "10", "--key", "CmdOrCtrl+L"], ["-Operation", "hotkey", "-WindowId", "10", "-Key", "CmdOrCtrl+L"]),
            ("type-text", ["computer", "type-text", "--window-id", "10", "--text", "hello"], ["-Operation", "type", "-WindowId", "10", "-Text", "hello"]),
            ("press-key", ["computer", "press-key", "--window-id", "10", "--key", "Return"], ["-Operation", "press", "-WindowId", "10", "-Key", "Return"]),
        ]

        mock_exe_info = {
            "win_path": r"C:\Temp\app.exe",
            "wsl_path": "/tmp/app.exe",
            "sha256": "sha",
        }
        response = {"ok": True, "result": {"action": "ok", "snapshot": {"treeText": ""}}}

        for op_name, args, expected_args in operations_data:
            with self.subTest(operation=op_name, backend="csharp"):
                with patch.dict(os.environ, {"AGODA_WINDOWS_UIA_IMPLEMENTATION": ""}, clear=False), patch(
                    "tools.agoda_portal_page_capture._ensure_csharp_bridge",
                    return_value=mock_exe_info,
                ), patch(
                    "tools.agoda_portal_page_capture._verify_csharp_bridge_executable"
                ), patch(
                    "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
                    return_value=contextlib.nullcontext(60.0),
                ), patch(
                    "tools.agoda_portal_page_capture.subprocess.run"
                ) as mock_run:
                    mock_run.return_value.returncode = 0
                    mock_run.return_value.stdout = json.dumps(response)
                    _run_windows_uia(*args)
                    spawn_cmd = mock_run.call_args[0][0]
                    self.assertEqual(spawn_cmd[0], "/tmp/app.exe")
                    self.assertEqual(spawn_cmd[1:], expected_args)

            with self.subTest(operation=op_name, backend="powershell"):
                with patch.dict(os.environ, {"AGODA_WINDOWS_UIA_IMPLEMENTATION": "powershell"}, clear=False), patch(
                    "tools.agoda_portal_page_capture._windows_uia_script_path",
                    return_value=r"C:\bridge\agoda_windows_uia_bridge.ps1",
                ), patch(
                    "tools.agoda_portal_page_capture._windows_uia_bridge_admission",
                    return_value=contextlib.nullcontext(60.0),
                ), patch(
                    "tools.agoda_portal_page_capture.subprocess.run"
                ) as mock_run:
                    mock_run.return_value.returncode = 0
                    mock_run.return_value.stdout = json.dumps(response)
                    _run_windows_uia(*args)
                    spawn_cmd = mock_run.call_args[0][0]
                    self.assertEqual(spawn_cmd[:6], ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", r"C:\bridge\agoda_windows_uia_bridge.ps1"])
                    self.assertEqual(spawn_cmd[6:], expected_args)

    def test_csharp_source_file_structure_and_parity(self) -> None:
        cs_path = Path(__file__).resolve().parents[2] / "tools" / "AgodaWindowsUiaBridge.cs"
        self.assertTrue(cs_path.is_file())
        content = cs_path.read_text(encoding="utf-8")

        self.assertIn("[STAThread]", content)
        self.assertIn("JavaScriptSerializer", content)
        self.assertIn("new UTF8Encoding(false)", content)
        for op in ("state", "click", "select", "hotkey", "type", "press"):
            self.assertIn(f'operation == "{op}"', content)
        expected_allowlist = [
            "window_not_found",
            "browser_omnibox_missing_or_ambiguous",
            "browser_content_root_missing_or_ambiguous",
            "semantic_action_target_missing_or_ambiguous",
            "element_not_found",
            "element_not_selectable",
            "window_not_focused",
            "browser_omnibox_not_focused",
            "unsupported_hotkey",
            "unsupported_key",
            "focused_value_receiver_missing",
        ]
        for code in expected_allowlist:
            self.assertIn(f'"{code}"', content)
        self.assertIn('"bridge_execution_failed"', content)


if __name__ == "__main__":
    unittest.main()

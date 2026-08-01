import unittest
from unittest import mock

from mapscan.win import session as sess


class QuadrantRectTest(unittest.TestCase):
    def test_top_right_quadrant_of_work_area(self):
        with mock.patch.object(sess.win32, "work_area", return_value=(0, 0, 5120, 1392)):
            self.assertEqual(sess.quadrant_scan_rect(1), (2560, 0, 2560, 696))

    def test_uses_monitor_origin_offset(self):
        with mock.patch.object(sess.win32, "work_area", return_value=(-1920, 40, 1920, 1000)):
            self.assertEqual(sess.quadrant_scan_rect(1), (-960, 40, 960, 500))


class PermissionTest(unittest.TestCase):
    def test_raises_when_target_elevated_and_self_not(self):
        s = sess.WindowSession(1)
        with mock.patch.object(sess.win32, "process_id", return_value=9), \
             mock.patch.object(sess.win32, "is_process_elevated", return_value=True), \
             mock.patch.object(sess.win32, "is_self_elevated", return_value=False):
            with self.assertRaises(sess.PermissionError_):
                s.check_permission()

    def test_passes_when_both_elevated(self):
        s = sess.WindowSession(1)
        with mock.patch.object(sess.win32, "process_id", return_value=9), \
             mock.patch.object(sess.win32, "is_process_elevated", return_value=True), \
             mock.patch.object(sess.win32, "is_self_elevated", return_value=True):
            s.check_permission()  # 예외 없음

    def test_passes_when_target_not_elevated(self):
        s = sess.WindowSession(1)
        with mock.patch.object(sess.win32, "process_id", return_value=9), \
             mock.patch.object(sess.win32, "is_process_elevated", return_value=False), \
             mock.patch.object(sess.win32, "is_self_elevated", return_value=False):
            s.check_permission()


class ScanRectLifecycleTest(unittest.TestCase):
    """FR-12 / AC-07: 스캔 크기 적용과 복원."""

    def setUp(self):
        self.original = (100, 200, 1294, 758)
        self.set_calls: list[tuple] = []

        def fake_set(hwnd, x, y, w, h):
            self.set_calls.append((x, y, w, h))
            return True

        self.patches = [
            mock.patch.object(sess.win32, "window_rect", return_value=self.original),
            mock.patch.object(sess.win32, "set_window_rect", side_effect=fake_set),
            mock.patch.object(sess.win32, "client_size", return_value=(2544, 657)),
            mock.patch.object(sess.win32, "work_area", return_value=(0, 0, 5120, 1392)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_apply_then_restore_returns_original_rect(self):
        s = sess.WindowSession(1)
        client = s.apply_scan_rect()
        self.assertEqual(client, (2544, 657))
        self.assertEqual(self.set_calls[0], (2560, 0, 2560, 696))

        self.assertTrue(s.restore())
        self.assertEqual(self.set_calls[-1], self.original)

    def test_restore_runs_on_context_exit_even_after_error(self):
        with self.assertRaises(ValueError):
            with sess.WindowSession(1) as s:
                s.apply_scan_rect()
                raise ValueError("스캔 중 오류")
        self.assertEqual(self.set_calls[-1], self.original)

    def test_restore_is_noop_without_apply(self):
        s = sess.WindowSession(1)
        self.assertTrue(s.restore())
        self.assertEqual(self.set_calls, [])

    def test_repeated_apply_keeps_first_original(self):
        s = sess.WindowSession(1)
        s.apply_scan_rect()
        s.apply_scan_rect((0, 0, 3000, 700))
        s.restore()
        self.assertEqual(self.set_calls[-1], self.original)

    def test_low_aspect_warns_but_succeeds(self):
        with mock.patch.object(sess.win32, "client_size", return_value=(1278, 719)):
            s = sess.WindowSession(1)
            with self.assertLogs(sess.log, level="WARNING") as logs:
                s.apply_scan_rect()
            self.assertIn("종횡비", logs.output[0])

    def test_restore_failure_is_reported_not_raised(self):
        s = sess.WindowSession(1)
        s.apply_scan_rect()
        with mock.patch.object(sess.win32, "set_window_rect", return_value=False), \
             mock.patch.object(sess.win32, "last_error", return_value=5):
            with self.assertLogs(sess.log, level="ERROR"):
                self.assertFalse(s.restore())


class AttachTest(unittest.TestCase):
    def _info(self, hwnd, pid):
        return sess.WindowInfo(hwnd=hwnd, title="삼국지-전략판 113.554", pid=pid,
                               rect=(0, 0, 1294, 758), client=(1278, 719), elevated=True)

    def test_ambiguous_windows_require_explicit_hwnd(self):
        found = [self._info(1, 10), self._info(2, 20)]
        with mock.patch.object(sess, "find_client_windows", return_value=found):
            with self.assertRaises(RuntimeError) as ctx:
                sess.WindowSession.attach()
            self.assertIn("--hwnd", str(ctx.exception))

    def test_no_window_raises(self):
        with mock.patch.object(sess, "find_client_windows", return_value=[]):
            with self.assertRaises(RuntimeError):
                sess.WindowSession.attach()

    def test_single_window_is_selected(self):
        with mock.patch.object(sess, "find_client_windows", return_value=[self._info(7, 10)]), \
             mock.patch.object(sess.WindowSession, "check_permission"):
            self.assertEqual(sess.WindowSession.attach().hwnd, 7)


if __name__ == "__main__":
    unittest.main()

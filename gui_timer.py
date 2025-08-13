# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QTimer
from datetime import datetime, timedelta


def _ensure_core_widgets(self) -> bool:
    needed = ["timer", "timer_label", "pause_button"]
    missing = [n for n in needed if not hasattr(self, n)]
    if missing and hasattr(self, "log_error"):
        self.log_error(f"Timer UI missing: {', '.join(missing)}")
    return not missing


def _stop_blink(self):
    """Stop paused blinking effect."""
    try:
        self._is_blinking = False
        if getattr(self, "_blink_timer", None):
            self._blink_timer.stop()
            self._blink_timer.deleteLater()
        if hasattr(self, "timer_label"):
            self.timer_label.setVisible(True)
    except Exception:
        pass
    finally:
        self._blink_timer = None


def _start_blink(self, interval_ms: int = 400):
    """Blink the timer label while paused."""
    _stop_blink(self)
    try:
        self._is_blinking = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(interval_ms)
        self._blink_timer.timeout.connect(lambda: self.timer_label.setVisible(not self.timer_label.isVisible()))
        self._blink_timer.start()
    except Exception:
        # Best-effort only
        self._blink_timer = None
        self._is_blinking = False


def _set_pause_ui(self, paused: bool):
    if hasattr(self, "pause_button"):
        self.pause_button.setText("Resume Timer" if paused else "Pause Timer")
        self.pause_button.setToolTip("Resume the show timer" if paused else "Pause the show timer")


def _ensure_aux_timers(self):
    """Create the periodic sell-rate refresher if needed."""
    if not hasattr(self, "_sellrate_timer") or self._sellrate_timer is None:
        try:
            self._sellrate_timer = QTimer(self)
            self._sellrate_timer.setInterval(10_000)  # 10s refresh
            self._sellrate_timer.timeout.connect(lambda: self.show_avg_sell_rate(show_message=False))
        except Exception:
            self._sellrate_timer = None


def start_show(self):
    """Start (or restart) the show, reset state, and start timers."""
    # Optional confirm if already running
    try:
        if getattr(self, "timer", None) and self.timer.isActive():
            # Avoid accidental restart mid-show
            resp = QMessageBox.question(self, "Restart Show?", "A show is already running.\nRestart the timer?",
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
    except Exception:
        pass

    if not _ensure_core_widgets(self):
        return

    _stop_blink(self)

    try:
        # Backend marker (also verifies DB connectivity)
        if hasattr(self, "bidder_manager") and self.bidder_manager:
            self.bidder_manager.start_show()

        # Reset local timer state
        self.show_start_time = datetime.now()
        self.elapsed_before_pause = timedelta(0)
        self.is_timer_paused = False

        # Kick timers
        self.timer.start(1000)
        _ensure_aux_timers(self)
        if getattr(self, "_sellrate_timer", None):
            self._sellrate_timer.start()

        # Initial paint + metrics
        self.update_timer_display()
        self.show_avg_sell_rate(show_message=False)

        _set_pause_ui(self, paused=False)
        QMessageBox.information(self, "Success", "Show started!")
        if hasattr(self, "log_info"):
            self.log_info("Show started via GUI")
    except Exception as e:
        if hasattr(self, "log_error"):
            self.log_error(f"Failed to start show: {e}", exc_info=True)
        QMessageBox.critical(self, "Error", f"Failed to start show: {e}")


def pause_timer(self):
    """Toggle pause/resume for the timer (with blink while paused)."""
    if not _ensure_core_widgets(self):
        return

    # If never started, ignore
    if getattr(self, "show_start_time", None) is None and not self.timer.isActive():
        return

    try:
        if getattr(self, "is_timer_paused", False):
            # Resume
            self.show_start_time = datetime.now()
            self.is_timer_paused = False
            self.timer.start(1000)
            _set_pause_ui(self, paused=False)
            _stop_blink(self)
            if getattr(self, "_sellrate_timer", None):
                self._sellrate_timer.start()
            if hasattr(self, "log_info"):
                self.log_info("Timer resumed")
        else:
            # Pause
            self.timer.stop()
            if getattr(self, "show_start_time", None):
                self.elapsed_before_pause += datetime.now() - self.show_start_time
            self.is_timer_paused = True
            _set_pause_ui(self, paused=True)
            _start_blink(self)
            if getattr(self, "_sellrate_timer", None):
                self._sellrate_timer.stop()
            if hasattr(self, "log_info"):
                self.log_info("Timer paused")
    except Exception as e:
        if hasattr(self, "log_error"):
            self.log_error(f"Failed to toggle pause: {e}")


def stop_timer(self):
    """Fully stop and reset the timer."""
    if not _ensure_core_widgets(self):
        return
    try:
        self.timer.stop()
        if getattr(self, "_sellrate_timer", None):
            self._sellrate_timer.stop()
        _stop_blink(self)

        self.show_start_time = None
        self.elapsed_before_pause = timedelta(0)
        self.is_timer_paused = False

        if hasattr(self, "timer_label"):
            self.timer_label.setText("00:00:00")
            self.timer_label.setVisible(True)
        _set_pause_ui(self, paused=False)

        if hasattr(self, "log_info"):
            self.log_info("Timer stopped")
    except Exception as e:
        if hasattr(self, "log_error"):
            self.log_error(f"Failed to stop timer: {e}")


def update_timer_display(self):
    """Update the timer label with elapsed time in HH:MM:SS."""
    # Don’t update while paused or before start
    if getattr(self, "show_start_time", None) is None or getattr(self, "is_timer_paused", False):
        return

    try:
        elapsed = datetime.now() - self.show_start_time + getattr(self, "elapsed_before_pause", timedelta(0))
        total = int(elapsed.total_seconds())
        if total < 0:
            total = 0
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        if hasattr(self, "log_info"):
            self.log_info(f"Updated timer display: {hours:02d}:{minutes:02d}:{seconds:02d}")
    except Exception as e:
        if hasattr(self, "log_error"):
            self.log_error(f"Failed to update timer display: {e}")
        self.timer_label.setText("00:00:00")


def bind_timer_methods(gui):
    """Bind timer-related methods to the GUI instance."""
    gui.start_show = start_show.__get__(gui, gui.__class__)
    gui.pause_timer = pause_timer.__get__(gui, gui.__class__)
    gui.stop_timer = stop_timer.__get__(gui, gui.__class__)
    gui.update_timer_display = update_timer_display.__get__(gui, gui.__class__)

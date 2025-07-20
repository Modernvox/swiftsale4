from PySide6.QtWidgets import QMessageBox
from datetime import datetime, timedelta

def start_show(self):
    """Start the show, reset blinking state, and start the timer."""
    self._is_blinking = False
    if self._blink_job is not None:
        try:
            self._blink_job.stop()
        except Exception:
            pass
        self._blink_job = None
    try:
        self.bidder_manager.start_show()
        self.show_avg_sell_rate(show_message=False)
        self.show_start_time = datetime.now()
        self.elapsed_before_pause = timedelta(0)
        self.is_timer_paused = False
        self.timer.start(1000)
        self.update_timer_display()
        QMessageBox.information(self, "Success", "Show started!")
        self.log_info("Show started via GUI")
    except Exception as e:
        self.log_error(f"Failed to start show: {e}", exc_info=True)
        QMessageBox.critical(self, "Error", f"Failed to start show: {e}")

def pause_timer(self):
    """Toggle pause/resume for the timer."""
    if not self.timer.isActive() and not self.is_timer_paused:
        return

    if self.is_timer_paused:
        self.show_start_time = datetime.now()
        self.is_timer_paused = False
        self.timer.start(1000)
        self.pause_button.setText("Pause Timer")
        self.log_info("Timer resumed")
    else:
        self.timer.stop()
        self.elapsed_before_pause += datetime.now() - self.show_start_time
        self.is_timer_paused = True
        self.pause_button.setText("Resume Timer")
        self.log_info("Timer paused")

def stop_timer(self):
    """Fully stop and reset the timer."""
    self.timer.stop()
    self.show_start_time = None
    self.elapsed_before_pause = timedelta(0)
    self.is_timer_paused = False
    self.timer_label.setText("00:00:00")
    self.pause_button.setText("Pause Timer")
    self.log_info("Timer stopped")

def update_timer_display(self):
    """Update the timer label with elapsed time in HH:MM:SS."""
    if self.show_start_time is None or self.is_timer_paused:
        return
    try:
        elapsed = datetime.now() - self.show_start_time + self.elapsed_before_pause
        hours = int(elapsed.total_seconds() // 3600)
        minutes = int((elapsed.total_seconds() % 3600) // 60)
        seconds = int(elapsed.total_seconds() % 60)
        self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.log_info(f"Updated timer display: {hours:02d}:{minutes:02d}:{seconds:02d}")
    except Exception as e:
        self.log_error(f"Failed to update timer display: {e}")
        self.timer_label.setText("00:00:00")

def bind_timer_methods(gui):
    """Bind timer-related methods to the GUI instance."""
    gui.start_show = start_show.__get__(gui, gui.__class__)
    gui.pause_timer = pause_timer.__get__(gui, gui.__class__)
    gui.stop_timer = stop_timer.__get__(gui, gui.__class__)
    gui.update_timer_display = update_timer_display.__get__(gui, gui.__class__)
import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QUrl, QObject, QThread, QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QSlider, QStyleFactory,
    QSizePolicy, QFileDialog, QProgressBar
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData
from PySide6.QtMultimediaWidgets import QVideoWidget
from ffmpeg_util import compress_mp4_to_target_size, clip_mp4
from PySide6.QtGui import QPalette


class DropZone(QLabel):
    fileDropped = Signal(str)

    def __init__(self) -> None:
        super().__init__("Drop an MP4 file here")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(60)
        self.setStyleSheet("border: 2px dashed #888; padding: 16px;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and p.lower().endswith(".mp4"):
                self.fileDropped.emit(os.path.abspath(p))
                break

class CompressWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        target_size_mb: float,
        in_path: str,
        out_path: str,
        trim_start_ms: int | None,
        trim_end_ms: int | None,
        operation: str,
    ) -> None:
        super().__init__()
        self.target_size_mb = target_size_mb
        self.in_path = in_path
        self.out_path = out_path
        self.trim_start_ms = trim_start_ms
        self.trim_end_ms = trim_end_ms
        self.operation = operation

    def run(self) -> None:
        try:
            if self.operation == "compress":
                compress_mp4_to_target_size(
                    self.in_path,
                    self.out_path,
                    self.trim_start_ms,
                    self.trim_end_ms,
                    self.target_size_mb,
                )
            elif self.operation == "clip":
                if self.trim_start_ms is None or self.trim_end_ms is None:
                    raise ValueError("Clip requires both Start and End trim points")
                clip_mp4(
                    self.in_path,
                    self.out_path,
                    self.trim_start_ms,
                    self.trim_end_ms,
                )
            else:
                raise ValueError(f"Unknown operation: {self.operation}")
            self.finished.emit(self.out_path)
        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Squeezy - MP4 Compressor for Discord")
        self.current_path: str | None = None
        self.last_open_dir: str = str(Path.home())
        self.trim_start_ms: int | None = None
        self.trim_end_ms: int | None = None

        layout = QVBoxLayout(self)
        self.drop = DropZone()
        self.select_btn = QPushButton("Select MP4 File")
        self.file_label = QLabel("No file selected")
        self.file_label.setAlignment(Qt.AlignCenter)

        # Video preview setup
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(240)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.hide()

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        # Media controls
        self.controls_widget = QWidget()
        self.controls_widget.hide()
        controls_layout = QHBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.set_position)
        
        self.time_label = QLabel("00:00 / 00:00")

        self.trim_label = QLabel("Start: --:--  End: --:--")
        self.trim_label.hide()
        
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.position_slider)
        controls_layout.addWidget(self.time_label)
        controls_layout.addWidget(self.trim_label)

        self.trim_controls = QWidget()
        self.trim_controls.hide()
        trim_controls_layout = QHBoxLayout(self.trim_controls)
        trim_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.set_start_btn = QPushButton("Set Start")
        self.set_end_btn = QPushButton("Set End")
        self.clear_trim_btn = QPushButton("Clear Selection")
        self.preview_btn = QPushButton()
        self.preview_btn.setCheckable(True)
        self.preview_btn.setEnabled(False)
        self.update_preview_button_text(False)
        self.set_start_btn.clicked.connect(self.set_trim_start)
        self.set_end_btn.clicked.connect(self.set_trim_end)
        self.clear_trim_btn.clicked.connect(self.clear_trim_selection)
        self.preview_btn.toggled.connect(self.preview_selection_toggled)
        trim_controls_layout.addWidget(self.set_start_btn)
        trim_controls_layout.addWidget(self.set_end_btn)
        trim_controls_layout.addWidget(self.clear_trim_btn)
        trim_controls_layout.addWidget(self.preview_btn)
        trim_controls_layout.addStretch(1)

        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.playbackStateChanged.connect(self.state_changed)

        self.btn = QPushButton("Compress to 50MB")
        self.btn.setEnabled(False)
        self.btn_10mb = QPushButton("Compress to 20MB")
        self.btn_10mb.setEnabled(False)
        self.clip_btn = QPushButton("Clip Only")
        self.clip_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()

        self.drop.fileDropped.connect(self.on_file_dropped)
        self.select_btn.clicked.connect(self.select_file)
        self.btn.clicked.connect(self.compress_current)
        self.btn_10mb.clicked.connect(self.compress_current_10mb)
        self.clip_btn.clicked.connect(self.clip_current)
        self.clear_btn.clicked.connect(self.clear_current)

        layout.addWidget(self.drop)
        layout.addWidget(self.select_btn)
        layout.addWidget(self.file_label)
        layout.addWidget(self.video_widget, stretch=1)
        layout.addWidget(self.controls_widget)
        layout.addWidget(self.trim_controls)
        layout.addWidget(self.btn)
        layout.addWidget(self.btn_10mb)
        layout.addWidget(self.clip_btn)
        layout.addWidget(self.clear_btn)
        layout.addWidget(self.progress_bar)

        self.resize(460, 540)

        self._compress_thread: QThread | None = None
        self._compress_worker: CompressWorker | None = None
        self._pending_auto_resize = False

    def select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select MP4 File",
            self.last_open_dir,
            "MP4 Files (*.mp4)",
        )
        if path:
            selected_path = Path(path)
            self.last_open_dir = str(selected_path.parent)
            self.on_file_dropped(path)

    def on_file_dropped(self, path: str) -> None:
        self.current_path = path
        self._pending_auto_resize = True
        self.file_label.setText(path)
        self.btn.setEnabled(True)
        self.btn_10mb.setEnabled(True)
        self.clip_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.drop.hide()
        self.select_btn.hide()
        self.trim_start_ms = None
        self.trim_end_ms = None
        self.update_trim_ui()
        
        # Load and show video preview
        self.media_player.setSource(QUrl.fromLocalFile(path))
        self.video_widget.show()
        self.controls_widget.show()
        self.trim_label.show()
        self.trim_controls.show()
        self.media_player.play()

    def clear_current(self) -> None:
        self.current_path = None
        self._pending_auto_resize = False
        self.file_label.setText("No file selected")
        self.btn.setEnabled(False)
        self.btn_10mb.setEnabled(False)
        self.clip_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.drop.show()
        self.select_btn.show()
        self.trim_start_ms = None
        self.trim_end_ms = None
        self.update_trim_ui()
        
        # Stop and hide video preview
        self.media_player.stop()
        self.video_widget.hide()
        self.controls_widget.hide()
        self.trim_label.hide()
        self.trim_controls.hide()

    @staticmethod
    def get_non_overwriting_output_path(path: Path) -> str:
        if not path.exists():
            return str(path)

        index = 2
        while True:
            candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
            if not candidate.exists():
                return str(candidate)
            index += 1

    def compress_current(self) -> None:
        if not self.current_path:
            QMessageBox.information(self, "No file", "Drop an MP4 file first.")
            return

        if not self.validate_trim_selection():
            return

        in_path = self.current_path
        p = Path(in_path)
        out_path = self.get_non_overwriting_output_path(p.with_name(p.stem + " - 50MB.mp4"))

        self.start_worker(49.5, in_path, out_path, "compress")

    def compress_current_10mb(self) -> None:
        if not self.current_path:
            QMessageBox.information(self, "No file", "Drop an MP4 file first.")
            return

        if not self.validate_trim_selection():
            return

        in_path = self.current_path
        p = Path(in_path)
        out_path = self.get_non_overwriting_output_path(p.with_name(p.stem + " - 20MB.mp4"))

        self.start_worker(19.4, in_path, out_path, "compress")

    def clip_current(self) -> None:
        if not self.current_path:
            QMessageBox.information(self, "No file", "Drop an MP4 file first.")
            return

        if not self.validate_trim_selection() or self.trim_start_ms is None or self.trim_end_ms is None:
            QMessageBox.information(self, "Clip", "Set both Start and End before clipping.")
            return

        in_path = self.current_path
        p = Path(in_path)
        out_path = self.get_non_overwriting_output_path(p.with_name(p.stem + " - clip.mp4"))

        self.start_worker(0.0, in_path, out_path, "clip")

    def start_worker(self, target_size_mb: float, in_path: str, out_path: str, operation: str) -> None:
        if self._compress_thread is not None:
            return

        self.btn.setEnabled(False)
        self.btn_10mb.setEnabled(False)
        self.clip_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.progress_bar.show()

        self._compress_thread = QThread()
        self._compress_worker = CompressWorker(
            target_size_mb,
            in_path,
            out_path,
            self.trim_start_ms,
            self.trim_end_ms,
            operation,
        )
        self._compress_worker.moveToThread(self._compress_thread)
        self._compress_thread.started.connect(self._compress_worker.run)
        self._compress_worker.finished.connect(self.on_compress_done)
        self._compress_worker.error.connect(self.on_compress_error)
        self._compress_worker.finished.connect(self._compress_thread.quit)
        self._compress_worker.error.connect(self._compress_thread.quit)
        self._compress_thread.finished.connect(self._compress_thread.deleteLater)
        self._compress_thread.start()

    def on_compress_done(self, out_path: str) -> None:
        self.cleanup_compress_thread()
        QMessageBox.information(self, "Done", f"Saved:\n{out_path}")

    def on_compress_error(self, message: str) -> None:
        self.cleanup_compress_thread()
        QMessageBox.critical(self, "Error", message)

    def cleanup_compress_thread(self) -> None:
        if self._compress_thread is not None:
            self._compress_thread.quit()
            self._compress_thread.wait()

        self._compress_worker = None
        self._compress_thread = None
        self.btn.setEnabled(True)
        self.btn_10mb.setEnabled(True)
        self.clip_btn.setEnabled(True)
        self.clear_btn.setEnabled(self.current_path is not None)
        self.progress_bar.hide()

    def toggle_play(self) -> None:
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            if self.preview_btn.isChecked() and self.trim_start_ms is not None:
                if self.trim_end_ms is not None and self.media_player.position() >= self.trim_end_ms:
                    self.media_player.setPosition(self.trim_start_ms)
                elif self.media_player.position() < self.trim_start_ms:
                    self.media_player.setPosition(self.trim_start_ms)
            self.media_player.play()

    def set_position(self, position: int) -> None:
        self.media_player.setPosition(position)

    def position_changed(self, position: int) -> None:
        self.position_slider.setValue(position)
        self.update_time_label(position, self.media_player.duration())

        if (
            self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and self.preview_btn.isChecked()
            and self.trim_end_ms is not None
            and position >= self.trim_end_ms
        ):
            self.media_player.pause()
            self.media_player.setPosition(self.trim_end_ms)

    def duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, duration)
        self.update_time_label(self.media_player.position(), duration)
        self.update_trim_ui()

        if self._pending_auto_resize and duration > 0:
            self.resize_window_for_video()
            self._pending_auto_resize = False

    def resize_window_for_video(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return

        screen_rect = screen.availableGeometry()
        max_window_w = int(screen_rect.width() * 0.5)
        max_window_h = int(screen_rect.height() * 0.5)

        current_video_w = max(self.video_widget.width(), 1)
        current_video_h = max(self.video_widget.height(), 1)
        chrome_w = max(self.width() - current_video_w, 80)
        chrome_h = max(self.height() - current_video_h, 220)

        max_video_w = max(320, max_window_w - chrome_w)
        max_video_h = max(180, max_window_h - chrome_h)

        aspect = 16 / 9
        resolution = self.media_player.metaData().value(QMediaMetaData.Key.Resolution)
        if resolution is not None and resolution.width() > 0 and resolution.height() > 0:
            aspect = resolution.width() / resolution.height()

        video_w = max_video_w
        video_h = int(video_w / aspect)
        if video_h > max_video_h:
            video_h = max_video_h
            video_w = int(video_h * aspect)

        window_w = video_w + chrome_w
        window_h = video_h + chrome_h
        self.resize(window_w, window_h)
        QTimer.singleShot(0, self.refine_window_for_video_aspect)

    def refine_window_for_video_aspect(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return

        resolution = self.media_player.metaData().value(QMediaMetaData.Key.Resolution)
        if resolution is None or resolution.width() <= 0 or resolution.height() <= 0:
            return

        current_video_w = self.video_widget.width()
        current_video_h = self.video_widget.height()
        if current_video_w <= 0 or current_video_h <= 0:
            return

        target_aspect = resolution.width() / resolution.height()
        current_aspect = current_video_w / current_video_h

        # If the preview area is wider than the video aspect, grow height to reduce side bars.
        if current_aspect <= target_aspect * 1.01:
            return

        desired_video_h = int(current_video_w / target_aspect)
        extra_video_h = desired_video_h - current_video_h
        if extra_video_h <= 0:
            return

        max_window_h = int(screen.availableGeometry().height() * 0.9)
        new_window_h = min(self.height() + extra_video_h, max_window_h)
        if new_window_h > self.height():
            self.resize(self.width(), new_window_h)

    def state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("Pause")
        else:
            self.play_btn.setText("Play")

    def update_time_label(self, position: int, duration: int) -> None:
        self.time_label.setText(f"{self.format_time(position)} / {self.format_time(duration)}")

    @staticmethod
    def format_time(ms: int | None) -> str:
        if ms is None or ms < 0:
            return "--:--"
        s = ms // 1000
        m, s = divmod(s, 60)
        return f"{m:02d}:{s:02d}"

    def update_trim_ui(self) -> None:
        start_text = self.format_time(self.trim_start_ms)
        end_text = self.format_time(self.trim_end_ms)
        self.trim_label.setText(f"Start: {start_text}  End: {end_text}")
        show_preview = self.trim_start_ms is not None and self.trim_end_ms is not None
        self.preview_btn.setEnabled(show_preview)
        if not show_preview and self.preview_btn.isChecked():
            self.preview_btn.setChecked(False)
        self.update_preview_button_text(self.preview_btn.isChecked())

    def update_preview_button_text(self, checked: bool) -> None:
        state = "ON" if checked else "OFF"
        self.preview_btn.setText(f"Preview Selection: {state}")

    def validate_trim_selection(self) -> bool:
        if self.trim_start_ms is None and self.trim_end_ms is None:
            return True
        if self.trim_start_ms is None or self.trim_end_ms is None:
            QMessageBox.information(self, "Trim", "Set both Start and End to trim.")
            return False

        duration = self.media_player.duration()
        if duration <= 0:
            QMessageBox.information(self, "Trim", "Video duration not ready yet.")
            return False

        start = self.trim_start_ms
        end = self.trim_end_ms
        if start < 0 or end < 0 or start > duration or end > duration:
            QMessageBox.information(self, "Trim", "Trim points must be within the video duration.")
            return False

        if start >= end:
            self.trim_start_ms, self.trim_end_ms = end, start
            self.update_trim_ui()

        if self.trim_start_ms >= self.trim_end_ms:
            QMessageBox.information(self, "Trim", "Start must be before End.")
            return False

        return True

    def set_trim_start(self) -> None:
        duration = self.media_player.duration()
        if duration <= 0:
            QMessageBox.information(self, "Trim", "Video duration not ready yet.")
            return
        self.trim_start_ms = max(0, min(self.media_player.position(), duration))
        if self.trim_end_ms is not None and self.trim_start_ms >= self.trim_end_ms:
            self.trim_start_ms, self.trim_end_ms = self.trim_end_ms, self.trim_start_ms
        self.update_trim_ui()

    def set_trim_end(self) -> None:
        duration = self.media_player.duration()
        if duration <= 0:
            QMessageBox.information(self, "Trim", "Video duration not ready yet.")
            return
        self.trim_end_ms = max(0, min(self.media_player.position(), duration))
        if self.trim_start_ms is not None and self.trim_start_ms >= self.trim_end_ms:
            self.trim_start_ms, self.trim_end_ms = self.trim_end_ms, self.trim_start_ms
        self.update_trim_ui()

    def clear_trim_selection(self) -> None:
        self.trim_start_ms = None
        self.trim_end_ms = None
        self.update_trim_ui()

    def preview_selection_toggled(self, checked: bool) -> None:
        self.update_preview_button_text(checked)
        if not checked:
            return

        if (
            not self.validate_trim_selection()
            or self.trim_start_ms is None
            or self.trim_end_ms is None
        ):
            self.preview_btn.setChecked(False)
            return

        self.media_player.setPosition(self.trim_start_ms)
        self.media_player.play()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    w = MainWindow()
    w.show()
    # pal = QApplication.palette()
    # base = pal.color(QPalette.Base)
    # text = pal.color(QPalette.Text)
    # print("Base:", base.getRgb(), "Text:", text.getRgb())
    # print("Style:", QApplication.style().objectName())
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

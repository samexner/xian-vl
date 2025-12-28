# !/usr/bin/env python3
"""
Xian - Real-time Video Game Translation Overlay
A PyQt6-based translation overlay for Linux Wayland KDE Plasma
"""

import sys
import json
import asyncio
import base64
from io import BytesIO
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass
from enum import Enum

import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QTextEdit, QCheckBox,
    QGroupBox, QSlider, QTabWidget, QListWidget, QListWidgetItem,
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QFrame
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QRect, QPoint, QSize,
    QSettings, pyqtSlot, QBuffer, QIODevice
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QFont, QScreen, QGuiApplication,
    QMouseEvent, QPaintEvent, QKeyEvent, QImage
)

try:
    # Try to import screenshot capability for Wayland
    import subprocess

    SCREENSHOT_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False


class TranslationMode(Enum):
    FULL_SCREEN = "full_screen"
    REGION_SELECT = "region_select"


@dataclass
class TranslationRegion:
    """Represents a region to be translated"""
    x: int
    y: int
    width: int
    height: int
    name: str = ""
    enabled: bool = True


@dataclass
class TranslationResult:
    """Result from translation API"""
    translated_text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0


class OllamaAPI:
    """Interface to local Ollama Qwen3-VL API"""

    def __init__(self, base_url: str = "http://192.168.0.162:11434"):
        self.base_url = base_url
        self.model = "qwen3-vl:8b-instruct"

    def is_available(self) -> bool:
        """Check if Ollama API is available"""
        try:
            url = self.base_url.rstrip('/') + "/api/tags"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except:
            return False

    def get_available_models(self) -> List[str]:
        """Fetch list of available models from Ollama"""
        try:
            url = self.base_url.rstrip('/') + "/api/tags"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [model['name'] for model in data.get('models', [])]
        except:
            pass
        return []

    def translate_image(self, image_data: bytes, source_lang: str = "auto",
                        target_lang: str = "English", mode: TranslationMode = TranslationMode.FULL_SCREEN) -> List[
        TranslationResult]:
        """Send image to Qwen3-VL for translation"""
        try:
            # Encode image to base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')

            if mode == TranslationMode.FULL_SCREEN:
                prompt = f"""<|im_start|>system
You are a helpful assistant that identifies and translates text in images. You must respond ONLY with a JSON object.
<|im_end|>
<|im_start|>user
<|vision_start|><|image_pad|><|vision_end|>Please analyze this game screenshot and translate any visible text from {source_lang} to {target_lang}. 
For each text element you find, provide:
1. The translated text
2. The approximate coordinates (x, y) where the text appears
3. The approximate width and height of the text area

Format your response as JSON with this structure:
{{
    "translations": [
        {{
            "translated_text": "translated text here",
            "x": x_coordinate,
            "y": y_coordinate,
            "width": text_width,
            "height": text_height,
            "confidence": confidence_score
        }}
    ]
}}
<|im_end|>
<|im_start|>assistant
"""
            else:
                prompt = f"""<|im_start|>system
You are a helpful assistant that translates text in images.
<|im_end|>
<|im_start|>user
<|vision_start|><|image_pad|><|vision_end|>Translate any text in this image from {source_lang} to {target_lang}. Return only the translated text.
<|im_end|>
<|im_start|>assistant
"""

            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "format": "json" if mode == TranslationMode.FULL_SCREEN else ""
            }

            # Ensure base_url doesn't have a trailing slash to avoid double slashes
            url = self.base_url.rstrip('/') + "/api/generate"
            
            response = requests.post(
                url,
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '')
                
                # Debug print for developers
                # print(f"API Response Content: {content}")

                if mode == TranslationMode.FULL_SCREEN:
                    results = self._parse_full_screen_response(content)
                    # Adjust for normalized coordinates (0-1000) if used by the model
                    # Qwen-VL models often use 1000x1000 normalized coordinates
                    # Let's check if the coordinates seem normalized
                    is_normalized = any(
                        0 < r.x <= 1000 and 0 < r.y <= 1000 
                        for r in results if r.x != 0 or r.y != 0
                    )
                    
                    if is_normalized:
                        screen = QGuiApplication.primaryScreen().geometry()
                        screen_width = screen.width()
                        screen_height = screen.height()
                        
                        for r in results:
                            r.x = int(r.x * screen_width / 1000)
                            r.y = int(r.y * screen_height / 1000)
                            r.width = int(r.width * screen_width / 1000)
                            r.height = int(r.height * screen_height / 1000)
                    
                    return results
                else:
                    return [TranslationResult(content, 0, 0, 100, 30)]
            elif response.status_code == 404:
                error_msg = f"API Error: 404 - Model '{self.model}' not found."
                try:
                    error_data = response.json()
                    if "not found" in error_data.get('error', '').lower():
                        error_msg += f"\nTry running: ollama pull {self.model}"
                except:
                    pass
                print(error_msg)
            else:
                print(f"API Error: {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"Error details: {error_data.get('error', 'No error message')}")
                except:
                    print(f"Error body: {response.text}")

        except Exception as e:
            print(f"Translation error: {e}")

        return []

    def _parse_full_screen_response(self, content: str) -> List[TranslationResult]:
        """Parse JSON response from full screen mode"""
        try:
            # Clean up content in case it's wrapped in markdown code blocks
            clean_content = content.strip()
            if clean_content.startswith("```json"):
                clean_content = clean_content[7:]
            elif clean_content.startswith("```"):
                clean_content = clean_content[3:]
            
            if clean_content.endswith("```"):
                clean_content = clean_content[:-3]
            
            clean_content = clean_content.strip()
            
            data = json.loads(clean_content)
            results = []

            for trans in data.get('translations', []):
                results.append(TranslationResult(
                    translated_text=trans.get('translated_text', ''),
                    x=trans.get('x', 0),
                    y=trans.get('y', 0),
                    width=trans.get('width', 100),
                    height=trans.get('height', 30),
                    confidence=trans.get('confidence', 1.0)
                ))

            return results
        except Exception as e:
            print(f"JSON Parsing error: {e}")
            print(f"Original content: {content}")
            # Fallback: treat as simple text
            return [TranslationResult(content, 100, 100, 200, 30)]


class ScreenCapture:
    """Handle screen capture on Wayland"""

    @staticmethod
    def capture_screen() -> Optional[bytes]:
        """Capture entire screen using spectacle or grim"""
        try:
            # Try spectacle first (KDE's screenshot tool)
            result = subprocess.run([
                'spectacle', '-b', '-n', '-o', '/tmp/xian_screenshot.png'
            ], capture_output=True, timeout=5)

            if result.returncode == 0:
                with open('/tmp/xian_screenshot.png', 'rb') as f:
                    return f.read()

            # Fallback to grim
            result = subprocess.run([
                'grim', '/tmp/xian_screenshot.png'
            ], capture_output=True, timeout=5)

            if result.returncode == 0:
                with open('/tmp/xian_screenshot.png', 'rb') as f:
                    return f.read()

        except Exception as e:
            print(f"Screenshot capture error: {e}")

        return None

    @staticmethod
    def capture_region(x: int, y: int, width: int, height: int) -> Optional[bytes]:
        """Capture specific screen region"""
        try:
            # Use grim for region capture
            result = subprocess.run([
                'grim', '-g', f'{x},{y} {width}x{height}', '/tmp/xian_region.png'
            ], capture_output=True, timeout=5)

            if result.returncode == 0:
                with open('/tmp/xian_region.png', 'rb') as f:
                    return f.read()

        except Exception as e:
            print(f"Region capture error: {e}")

        return None

    @staticmethod
    def compress_image(image_data: bytes, quality: int = 75) -> bytes:
        """Compress image to JPEG with specified quality"""
        try:
            image = QImage.fromData(image_data)
            if image.isNull():
                return image_data

            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "JPG", quality)
            return buffer.data().data()
        except Exception as e:
            print(f"Compression error: {e}")
            return image_data


class RegionSelector(QWidget):
    """Widget for selecting screen regions"""

    region_selected = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 100);")

        self.start_pos = QPoint()
        self.current_pos = QPoint()
        self.selecting = False

        # Make fullscreen
        screen = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.pos()
            self.selecting = True

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.selecting:
            self.current_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.selecting:
            self.selecting = False

            # Calculate selection rectangle
            rect = QRect(self.start_pos, self.current_pos).normalized()
            if rect.width() > 10 and rect.height() > 10:
                self.region_selected.emit(rect)

            self.close()

    def paintEvent(self, event: QPaintEvent):
        if self.selecting:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(255, 0, 0), 2))
            painter.drawRect(QRect(self.start_pos, self.current_pos))

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()


class TranslationOverlay(QWidget):
    """Translucent overlay window for displaying translations"""

    def __init__(self):
        super().__init__()
        self.translations = []
        self.setup_ui()

    def setup_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Make fullscreen but click-through
        screen = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # Enable mouse passthrough
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def update_translations(self, translations: List[TranslationResult]):
        """Update displayed translations"""
        self.translations = translations
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Arial", 12, QFont.Weight.Bold)
        painter.setFont(font)

        # Get opacity from settings
        settings = QSettings("Xian", "VideoGameTranslator")
        opacity_val = int(settings.value("opacity", 80))
        opacity = int(opacity_val * 2.55)

        for translation in self.translations:
            # Draw background
            painter.setBrush(QColor(0, 0, 0, opacity))
            painter.setPen(Qt.PenStyle.NoPen)

            # Add padding to the box
            padding = 10
            rect = QRect(
                translation.x - padding, translation.y - padding,
                translation.width + (padding * 2), translation.height + (padding * 2)
            )
            
            # Ensure the box is large enough for some text even if the model gave a tiny box
            if rect.width() < 100: rect.setWidth(100)
            if rect.height() < 40: rect.setHeight(40)
            
            painter.drawRoundedRect(rect, 5, 5)

            # Draw text
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                translation.translated_text
            )


class TranslationWorker(QThread):
    """Worker thread for handling translations"""

    translation_ready = pyqtSignal(list)
    request_hide_overlay = pyqtSignal()
    request_show_overlay = pyqtSignal()

    def __init__(self, ollama_api: OllamaAPI):
        super().__init__()
        self.ollama_api = ollama_api
        self.running = False
        self.mode = TranslationMode.FULL_SCREEN
        self.regions = []
        self.source_lang = "auto"
        self.target_lang = "English"
        self.interval = 2000  # ms

    def set_config(self, mode: TranslationMode, regions: List[TranslationRegion],
                   source_lang: str, target_lang: str, interval: int):
        self.mode = mode
        self.regions = regions
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.interval = interval

    def start_translation(self):
        self.running = True
        self.start()

    def stop_translation(self):
        self.running = False
        self.quit()
        self.wait()

    def run(self):
        while self.running:
            try:
                if self.mode == TranslationMode.FULL_SCREEN:
                    self._translate_full_screen()
                else:
                    self._translate_regions()

                self.msleep(self.interval)

            except Exception as e:
                print(f"Translation worker error: {e}")
                self.msleep(5000)  # Wait longer on error

    def _translate_full_screen(self):
        """Handle full screen translation"""
        self.request_hide_overlay.emit()
        self.msleep(100)  # Wait for overlay to hide
        image_data = ScreenCapture.capture_screen()
        self.request_show_overlay.emit()
        
        if image_data:
            # Compress image before sending to API
            compressed_data = ScreenCapture.compress_image(image_data)
            
            results = self.ollama_api.translate_image(
                compressed_data, self.source_lang, self.target_lang, self.mode
            )
            if results:
                self.translation_ready.emit(results)

    def _translate_regions(self):
        """Handle region-based translation"""
        self.request_hide_overlay.emit()
        self.msleep(100)  # Wait for overlay to hide
        
        all_results = []
        any_captured = False

        for region in self.regions:
            if not region.enabled:
                continue

            image_data = ScreenCapture.capture_region(
                region.x, region.y, region.width, region.height
            )

            if image_data:
                any_captured = True
                # Compress image before sending to API
                compressed_data = ScreenCapture.compress_image(image_data)
                
                results = self.ollama_api.translate_image(
                    compressed_data, self.source_lang, self.target_lang, TranslationMode.REGION_SELECT
                )

                # Adjust coordinates for region
                for result in results:
                    result.x += region.x
                    result.y += region.y
                    all_results.append(result)

        self.request_show_overlay.emit()
        
        if all_results:
            self.translation_ready.emit(all_results)


class APIStatusWorker(QThread):
    """Worker thread for checking API status and fetching models"""
    status_changed = pyqtSignal(bool, list)

    def __init__(self, ollama_api: OllamaAPI):
        super().__init__()
        self.ollama_api = ollama_api

    def run(self):
        is_available = self.ollama_api.is_available()
        models = []
        if is_available:
            models = self.ollama_api.get_available_models()
        self.status_changed.emit(is_available, models)


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.ollama_api = OllamaAPI()
        self.translation_worker = TranslationWorker(self.ollama_api)
        self.api_status_worker = APIStatusWorker(self.ollama_api)
        self.translation_overlay = TranslationOverlay()
        self.region_selector = None
        self.regions = []
        self.settings = QSettings("Xian", "VideoGameTranslator")

        # Debounce timer for API status checks
        self.api_check_timer = QTimer()
        self.api_check_timer.setSingleShot(True)
        self.api_check_timer.setInterval(1000)  # 1 second debounce
        self.api_check_timer.timeout.connect(self._do_api_status_check)

        self.setup_ui()
        self.connect_signals()
        self.load_settings()

        # Check API availability
        self.check_api_status()

    def setup_ui(self):
        self.setWindowTitle("Xian - Video Game Translation Overlay")
        self.setFixedSize(600, 500)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Create tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # General tab
        general_tab = self._create_general_tab()
        tabs.addTab(general_tab, "General")

        # Regions tab
        regions_tab = self._create_regions_tab()
        tabs.addTab(regions_tab, "Regions")

        # Settings tab
        settings_tab = self._create_settings_tab()
        tabs.addTab(settings_tab, "Settings")

        # Control buttons
        controls_layout = QHBoxLayout()

        self.start_button = QPushButton("Start Translation")
        self.stop_button = QPushButton("Stop Translation")
        self.stop_button.setEnabled(False)

        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addStretch()

        self.status_label = QLabel("Ready")
        controls_layout.addWidget(self.status_label)

        layout.addLayout(controls_layout)

    def _create_general_tab(self) -> QWidget:
        """Create general settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Translation mode
        mode_group = QGroupBox("Translation Mode")
        mode_layout = QVBoxLayout(mode_group)

        self.full_screen_radio = QCheckBox("Full Screen Analysis")
        self.region_select_radio = QCheckBox("Region Selection")
        self.full_screen_radio.setChecked(True)

        mode_layout.addWidget(self.full_screen_radio)
        mode_layout.addWidget(self.region_select_radio)

        layout.addWidget(mode_group)

        # Language settings
        lang_group = QGroupBox("Languages")
        lang_layout = QFormLayout(lang_group)

        self.source_lang_combo = QComboBox()
        self.source_lang_combo.addItems(["auto", "Japanese", "Korean", "Chinese", "Spanish", "French"])

        self.target_lang_combo = QComboBox()
        self.target_lang_combo.addItems(["English", "Japanese", "Korean", "Chinese", "Spanish", "French"])

        lang_layout.addRow("Source Language:", self.source_lang_combo)
        lang_layout.addRow("Target Language:", self.target_lang_combo)

        layout.addWidget(lang_group)

        # Timing settings
        timing_group = QGroupBox("Timing")
        timing_layout = QFormLayout(timing_group)

        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(500, 10000)
        self.interval_spinbox.setValue(2000)
        self.interval_spinbox.setSuffix(" ms")

        timing_layout.addRow("Update Interval:", self.interval_spinbox)

        layout.addWidget(timing_group)

        layout.addStretch()
        return widget

    def _create_regions_tab(self) -> QWidget:
        """Create region management tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Region list
        self.regions_list = QListWidget()
        layout.addWidget(QLabel("Translation Regions:"))
        layout.addWidget(self.regions_list)

        # Region controls
        controls_layout = QHBoxLayout()

        self.add_region_button = QPushButton("Add Region")
        self.remove_region_button = QPushButton("Remove Region")
        self.test_region_button = QPushButton("Test Region")

        controls_layout.addWidget(self.add_region_button)
        controls_layout.addWidget(self.remove_region_button)
        controls_layout.addWidget(self.test_region_button)
        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        return widget

    def _create_settings_tab(self) -> QWidget:
        """Create settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # API settings
        api_group = QGroupBox("Ollama API")
        api_layout = QFormLayout(api_group)

        self.api_url_edit = QLineEdit("http://192.168.0.162:11434")
        self.api_model_edit = QComboBox()
        self.api_model_edit.setEditable(True)
        self.api_model_edit.addItem("qwen3-vl:8b-instruct")
        self.api_status_label = QLabel("Checking...")

        api_layout.addRow("API URL:", self.api_url_edit)
        api_layout.addRow("Model:", self.api_model_edit)
        api_layout.addRow("Status:", self.api_status_label)

        layout.addWidget(api_group)

        # Overlay settings
        overlay_group = QGroupBox("Overlay")
        overlay_layout = QFormLayout(overlay_group)

        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(50, 100)
        self.overlay_opacity_slider.setValue(80)

        overlay_layout.addRow("Opacity:", self.overlay_opacity_slider)

        layout.addWidget(overlay_group)

        # Clear settings button
        self.reset_button = QPushButton("Reset All Settings")
        self.reset_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        layout.addWidget(self.reset_button)

        layout.addStretch()
        return widget

    def connect_signals(self):
        """Connect UI signals"""
        self.start_button.clicked.connect(self.start_translation)
        self.stop_button.clicked.connect(self.stop_translation)
        self.add_region_button.clicked.connect(self.add_region)
        self.remove_region_button.clicked.connect(self.remove_region)
        self.test_region_button.clicked.connect(self.test_region)
        self.reset_button.clicked.connect(self.reset_settings)

        self.full_screen_radio.toggled.connect(self.on_mode_changed)
        self.region_select_radio.toggled.connect(self.on_mode_changed)

        self.api_url_edit.textChanged.connect(self.check_api_status)
        self.api_model_edit.editTextChanged.connect(self.check_api_status)

        self.api_status_worker.status_changed.connect(self._on_api_status_changed)

        self.translation_worker.translation_ready.connect(
            self.translation_overlay.update_translations
        )
        self.translation_worker.request_hide_overlay.connect(
            self.translation_overlay.hide
        )
        self.translation_worker.request_show_overlay.connect(
            self.translation_overlay.show
        )

    def check_api_status(self):
        """Start the API status check process with debouncing"""
        self.api_status_label.setText("Checking...")
        self.api_status_label.setStyleSheet("color: gray")
        self.api_check_timer.start()

    def _do_api_status_check(self):
        """Perform the actual API status check in a background thread"""
        self.ollama_api.base_url = self.api_url_edit.text()
        self.ollama_api.model = self.api_model_edit.currentText()
        
        if self.api_status_worker.isRunning():
            self.api_status_worker.terminate()
            self.api_status_worker.wait()
            
        self.api_status_worker.start()

    def _on_api_status_changed(self, is_available: bool, models: list):
        """Handle the result of the API status check"""
        if is_available:
            self.api_status_label.setText("✓ Connected")
            self.api_status_label.setStyleSheet("color: green")
            
            # Update models list if we got any
            if models:
                current_model = self.api_model_edit.currentText()
                self.api_model_edit.blockSignals(True)
                self.api_model_edit.clear()
                self.api_model_edit.addItems(models)
                self.api_model_edit.setCurrentText(current_model)
                self.api_model_edit.blockSignals(False)
        else:
            self.api_status_label.setText("✗ Disconnected")
            self.api_status_label.setStyleSheet("color: red")

    def on_mode_changed(self):
        """Handle translation mode change"""
        # Ensure only one mode is selected
        if self.sender() == self.full_screen_radio:
            if self.full_screen_radio.isChecked():
                self.region_select_radio.setChecked(False)
        else:
            if self.region_select_radio.isChecked():
                self.full_screen_radio.setChecked(False)

        # Ensure at least one is checked
        if not self.full_screen_radio.isChecked() and not self.region_select_radio.isChecked():
            self.full_screen_radio.setChecked(True)

    def add_region(self):
        """Add new translation region"""
        self.region_selector = RegionSelector()
        self.region_selector.region_selected.connect(self.on_region_selected)
        self.region_selector.show()

    def on_region_selected(self, rect: QRect):
        """Handle new region selection"""
        region = TranslationRegion(
            rect.x(), rect.y(), rect.width(), rect.height(),
            f"Region {len(self.regions) + 1}"
        )
        self.regions.append(region)
        self.update_regions_list()

    def remove_region(self):
        """Remove selected region"""
        current_row = self.regions_list.currentRow()
        if 0 <= current_row < len(self.regions):
            del self.regions[current_row]
            self.update_regions_list()

    def test_region(self):
        """Test translation on selected region"""
        current_row = self.regions_list.currentRow()
        if 0 <= current_row < len(self.regions):
            region = self.regions[current_row]
            # TODO: Implement region testing
            print(f"Testing region: {region.name}")

    def update_regions_list(self):
        """Update regions list display"""
        self.regions_list.clear()
        for region in self.regions:
            item_text = f"{region.name} ({region.x}, {region.y}, {region.width}x{region.height})"
            item = QListWidgetItem(item_text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if region.enabled else Qt.CheckState.Unchecked)
            self.regions_list.addItem(item)

    def start_translation(self):
        """Start translation process"""
        self.ollama_api.base_url = self.api_url_edit.text()
        self.ollama_api.model = self.api_model_edit.currentText()
        
        if not self.ollama_api.is_available():
            self.status_label.setText("Error: Ollama API not available")
            return

        # Configure worker
        mode = TranslationMode.FULL_SCREEN if self.full_screen_radio.isChecked() else TranslationMode.REGION_SELECT

        self.translation_worker.set_config(
            mode=mode,
            regions=self.regions,
            source_lang=self.source_lang_combo.currentText(),
            target_lang=self.target_lang_combo.currentText(),
            interval=self.interval_spinbox.value()
        )

        # Start translation
        self.translation_worker.start_translation()
        self.translation_overlay.show()

        # Update UI
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Translating...")

    def stop_translation(self):
        """Stop translation process"""
        self.translation_worker.stop_translation()
        self.translation_overlay.hide()

        # Update UI
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Ready")

    def reset_settings(self):
        """Reset all settings to default values"""
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self, 'Reset Settings',
            "Are you sure you want to reset all settings to their default values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.settings.clear()
            # Reload settings will fall back to defaults since they are cleared
            self.load_settings()
            # Additional UI cleanup that load_settings might not fully cover
            self.regions = []
            self.update_regions_list()
            self.check_api_status()
            self.status_label.setText("Settings Reset")

    def load_settings(self):
        """Load application settings"""
        self.api_url_edit.setText(self.settings.value("api_url", "http://192.168.0.162:11434"))
        self.api_model_edit.setCurrentText(self.settings.value("api_model", "qwen3-vl:8b-instruct"))
        self.source_lang_combo.setCurrentText(self.settings.value("source_lang", "auto"))
        self.target_lang_combo.setCurrentText(self.settings.value("target_lang", "English"))
        self.interval_spinbox.setValue(int(self.settings.value("interval", 2000)))
        self.overlay_opacity_slider.setValue(int(self.settings.value("opacity", 80)))
        
        # Sync API object
        self.ollama_api.base_url = self.api_url_edit.text()
        self.ollama_api.model = self.api_model_edit.currentText()
        
        # Load regions
        regions_json = self.settings.value("regions", "")
        if regions_json:
            try:
                regions_data = json.loads(regions_json)
                self.regions = [TranslationRegion(**r) for r in regions_data]
                self.update_regions_list()
            except Exception as e:
                print(f"Error loading regions: {e}")

    def save_settings(self):
        """Save application settings"""
        self.settings.setValue("api_url", self.api_url_edit.text())
        self.settings.setValue("api_model", self.api_model_edit.currentText())
        self.settings.setValue("source_lang", self.source_lang_combo.currentText())
        self.settings.setValue("target_lang", self.target_lang_combo.currentText())
        self.settings.setValue("interval", self.interval_spinbox.value())
        self.settings.setValue("opacity", self.overlay_opacity_slider.value())
        
        # Save regions
        regions_data = [
            {
                "x": r.x,
                "y": r.y,
                "width": r.width,
                "height": r.height,
                "name": r.name,
                "enabled": r.enabled
            }
            for r in self.regions
        ]
        self.settings.setValue("regions", json.dumps(regions_data))

    def closeEvent(self, event):
        """Handle application close"""
        self.stop_translation()
        self.save_settings()
        event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)

    # Check for required dependencies
    if not SCREENSHOT_AVAILABLE:
        print("Warning: Screenshot dependencies not available")

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

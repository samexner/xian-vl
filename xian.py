#!/usr/bin/env python3

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
    QSettings, pyqtSlot
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QFont, QScreen, QGuiApplication,
    QMouseEvent, QPaintEvent, QKeyEvent
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
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.model = "qwen2-vl"
    
    def is_available(self) -> bool:
        """Check if Ollama API is available"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def translate_image(self, image_data: bytes, source_lang: str = "auto", 
                       target_lang: str = "English", mode: TranslationMode = TranslationMode.FULL_SCREEN) -> List[TranslationResult]:
        """Send image to Qwen3-VL for translation"""
        try:
            # Encode image to base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
            if mode == TranslationMode.FULL_SCREEN:
                prompt = f"""Please analyze this game screenshot and translate any visible text from {source_lang} to {target_lang}. 
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
                }}"""
            else:
                prompt = f"""Translate any text in this image from {source_lang} to {target_lang}. Return only the translated text."""
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64]
                    }
                ],
                "stream": False
            }
            
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('message', {}).get('content', '')
                
                if mode == TranslationMode.FULL_SCREEN:
                    return self._parse_full_screen_response(content)
                else:
                    return [TranslationResult(content, 0, 0, 100, 30)]
            
        except Exception as e:
            print(f"Translation error: {e}")
        
        return []
    
    def _parse_full_screen_response(self, content: str) -> List[TranslationResult]:
        """Parse JSON response from full screen mode"""
        try:
            data = json.loads(content)
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
        except:
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
            Qt.WindowType.Tool
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
        
        for translation in self.translations:
            # Draw background
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(Qt.PenStyle.NoPen)
            
            rect = QRect(
                translation.x, translation.y,
                translation.width, translation.height
            )
            painter.drawRoundedRect(rect, 5, 5)
            
            # Draw text
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                translation.translated_text
            )


class TranslationWorker(QThread):
    """Worker thread for handling translations"""
    
    translation_ready = pyqtSignal(list)
    
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
        image_data = ScreenCapture.capture_screen()
        if image_data:
            results = self.ollama_api.translate_image(
                image_data, self.source_lang, self.target_lang, self.mode
            )
            if results:
                self.translation_ready.emit(results)
    
    def _translate_regions(self):
        """Handle region-based translation"""
        all_results = []
        
        for region in self.regions:
            if not region.enabled:
                continue
                
            image_data = ScreenCapture.capture_region(
                region.x, region.y, region.width, region.height
            )
            
            if image_data:
                results = self.ollama_api.translate_image(
                    image_data, self.source_lang, self.target_lang, TranslationMode.REGION_SELECT
                )
                
                # Adjust coordinates for region
                for result in results:
                    result.x += region.x
                    result.y += region.y
                    all_results.append(result)
        
        if all_results:
            self.translation_ready.emit(all_results)


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.ollama_api = OllamaAPI()
        self.translation_worker = TranslationWorker(self.ollama_api)
        self.translation_overlay = TranslationOverlay()
        self.region_selector = None
        self.regions = []
        self.settings = QSettings("Xian", "VideoGameTranslator")
        
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
        
        self.api_url_edit = QLineEdit("http://localhost:11434")
        self.api_model_edit = QLineEdit("qwen2-vl")
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
        
        layout.addStretch()
        return widget
    
    def connect_signals(self):
        """Connect UI signals"""
        self.start_button.clicked.connect(self.start_translation)
        self.stop_button.clicked.connect(self.stop_translation)
        self.add_region_button.clicked.connect(self.add_region)
        self.remove_region_button.clicked.connect(self.remove_region)
        self.test_region_button.clicked.connect(self.test_region)
        
        self.full_screen_radio.toggled.connect(self.on_mode_changed)
        self.region_select_radio.toggled.connect(self.on_mode_changed)
        
        self.translation_worker.translation_ready.connect(
            self.translation_overlay.update_translations
        )
    
    def check_api_status(self):
        """Check if Ollama API is available"""
        if self.ollama_api.is_available():
            self.api_status_label.setText("✓ Connected")
            self.api_status_label.setStyleSheet("color: green")
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
    
    def load_settings(self):
        """Load application settings"""
        # TODO: Implement settings loading
        pass
    
    def save_settings(self):
        """Save application settings"""
        # TODO: Implement settings saving
        pass
    
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

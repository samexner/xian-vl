import json
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSpinBox, QCheckBox, QGroupBox, QSlider, QTabWidget,
    QListWidget, QListWidgetItem, QFormLayout, QLineEdit, QSystemTrayIcon, QMenu,
    QApplication
)
from PyQt6.QtCore import Qt, QTimer, QRect, QSettings, pyqtSlot
from PyQt6.QtGui import QIcon, QShortcut, QKeySequence

from .api import OllamaAPI
from .workers import TranslationWorker, APIStatusWorker
from .overlay import TranslationOverlay
from .selector import RegionSelector
from .models import TranslationMode, TranslationRegion

class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon("xian.png"))
        self.ollama_api = OllamaAPI()
        self.translation_worker = TranslationWorker(self.ollama_api)
        self.api_status_worker = APIStatusWorker(self.ollama_api)
        self.translation_overlay = TranslationOverlay(self)
        self.region_selector = None
        self.regions = []
        self.settings = QSettings("Xian", "VideoGameTranslator")

        # Debounce timer for API status checks
        self.api_check_timer = QTimer()
        self.api_check_timer.setSingleShot(True)
        self.api_check_timer.setInterval(1000)  # 1 second debounce
        self.api_check_timer.timeout.connect(self._do_api_status_check)

        self.setup_ui()
        self.setup_tray_icon()
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

    def setup_tray_icon(self):
        """Initialize system tray icon and menu"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("xian.png"))
        
        tray_menu = QMenu()
        
        self.tray_show_action = tray_menu.addAction("Show Settings")
        self.tray_show_action.triggered.connect(self.show_and_activate)
        
        tray_menu.addSeparator()
        
        self.tray_toggle_action = tray_menu.addAction("Start Translation")
        self.tray_toggle_action.triggered.connect(self.toggle_translation)
        
        self.tray_clear_action = tray_menu.addAction("Clear Translations")
        self.tray_clear_action.triggered.connect(self.clear_all_translations)
        
        tray_menu.addSeparator()
        
        self.tray_quit_action = tray_menu.addAction("Quit")
        self.tray_quit_action.triggered.connect(QApplication.instance().quit)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_and_activate()

    def show_and_activate(self):
        self.show()
        self.activateWindow()
        self.raise_()

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

        # UI behavior settings
        ui_group = QGroupBox("UI Behavior")
        ui_layout = QVBoxLayout(ui_group)
        self.minimize_on_start_checkbox = QCheckBox("Minimize to Tray on Start")
        self.minimize_on_start_checkbox.setChecked(True)
        ui_layout.addWidget(self.minimize_on_start_checkbox)
        layout.addWidget(ui_group)

        # Clear translations button
        self.clear_translations_button = QPushButton("Clear All Translations (Ctrl+L)")
        self.clear_translations_button.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold;")
        layout.addWidget(self.clear_translations_button)

        self.hide_overlay_checkbox = QCheckBox("Hide All Translations (Ctrl+H)")
        self.hide_overlay_checkbox.setToolTip("Temporarily hide all translation bubbles from the screen")
        layout.addWidget(self.hide_overlay_checkbox)

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
        self.api_model_edit.addItem("qwen3-vl:2b-instruct")
        self.api_model_edit.addItem("qwen3-vl:8b-instruct")
        self.api_model_edit.setToolTip("Ollama model name. 'qwen3-vl:2b-instruct' is recommended for performance.")
        self.api_status_label = QLabel("Checking...")

        api_layout.addRow("API URL:", self.api_url_edit)
        api_layout.addRow("Model:", self.api_model_edit)
        api_layout.addRow("Status:", self.api_status_label)

        layout.addWidget(api_group)

        # Performance settings
        perf_group = QGroupBox("Performance (Local LLM)")
        perf_layout = QFormLayout(perf_group)

        self.num_thread_spin = QSpinBox()
        self.num_thread_spin.setRange(0, 64)
        self.num_thread_spin.setSpecialValueText("Auto")
        self.num_thread_spin.setToolTip("Number of CPU threads to use (0 = auto)")

        self.num_gpu_spin = QSpinBox()
        self.num_gpu_spin.setRange(0, 99)
        self.num_gpu_spin.setValue(99)
        self.num_gpu_spin.setToolTip("Number of layers to offload to GPU. Set high to offload the whole model.")

        self.api_timeout_spin = QSpinBox()
        self.api_timeout_spin.setRange(10, 600)
        self.api_timeout_spin.setValue(60)
        self.api_timeout_spin.setSuffix(" s")
        self.api_timeout_spin.setToolTip("Request timeout in seconds. Increase if getting read timeouts.")

        self.keep_alive_checkbox = QCheckBox("Keep Model Loaded")
        self.keep_alive_checkbox.setChecked(True)
        self.keep_alive_checkbox.setToolTip("Keep model in GPU memory after request (Recommended for speed)")

        perf_layout.addRow("CPU Threads:", self.num_thread_spin)
        perf_layout.addRow("GPU Layers:", self.num_gpu_spin)
        perf_layout.addRow("API Timeout:", self.api_timeout_spin)
        perf_layout.addRow(self.keep_alive_checkbox)

        layout.addWidget(perf_group)

        # Overlay settings
        overlay_group = QGroupBox("Overlay")
        overlay_layout = QFormLayout(overlay_group)

        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(50, 100)
        self.overlay_opacity_slider.setValue(80)

        overlay_layout.addRow("Opacity:", self.overlay_opacity_slider)

        self.debug_mode_checkbox = QCheckBox("Enable Debug Mode (Show raw API boxes)")
        overlay_layout.addRow(self.debug_mode_checkbox)

        self.redaction_margin_spin = QSpinBox()
        self.redaction_margin_spin.setRange(0, 100)
        self.redaction_margin_spin.setValue(15)
        self.redaction_margin_spin.setSuffix(" px")
        self.redaction_margin_spin.setToolTip("Margin for redacting existing translations. Increase if getting duplicate translations.")
        overlay_layout.addRow("Redaction Margin:", self.redaction_margin_spin)

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
        self.clear_translations_button.clicked.connect(self.clear_all_translations)
        self.hide_overlay_checkbox.toggled.connect(self.toggle_overlay_visibility)

        # Shortcuts
        self.clear_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.clear_shortcut.activated.connect(self.clear_all_translations)
        
        self.hide_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        self.hide_shortcut.activated.connect(lambda: self.hide_overlay_checkbox.setChecked(not self.hide_overlay_checkbox.isChecked()))

        self.start_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.start_shortcut.activated.connect(self.toggle_translation)

        self.full_screen_radio.toggled.connect(self.on_mode_changed)
        self.region_select_radio.toggled.connect(self.on_mode_changed)

        self.api_url_edit.textChanged.connect(self.check_api_status)
        self.api_model_edit.editTextChanged.connect(self.check_api_status)

        self.debug_mode_checkbox.toggled.connect(self.save_settings)
        self.overlay_opacity_slider.valueChanged.connect(self.save_settings)
        self.redaction_margin_spin.valueChanged.connect(self.save_settings)
        self.num_thread_spin.valueChanged.connect(self.save_settings)
        self.num_gpu_spin.valueChanged.connect(self.save_settings)
        self.api_timeout_spin.valueChanged.connect(self.save_settings)
        self.keep_alive_checkbox.toggled.connect(self.save_settings)
        self.minimize_on_start_checkbox.toggled.connect(self.save_settings)

        self.api_status_worker.status_changed.connect(self._on_api_status_changed)

        self.translation_worker.translation_ready.connect(
            self.translation_overlay.update_translations
        )
        self.translation_worker.request_hide_overlay.connect(
            self.on_translation_worker_capture_prepare
        )
        self.translation_worker.request_show_overlay.connect(
            self.translation_overlay.show
        )

    def on_translation_worker_capture_prepare(self):
        """Handle worker preparing for capture: update geometries (used to hide)"""
        # Update worker with latest bubble geometries for redaction
        geoms = self.translation_overlay.get_bubble_geometries()
        self.translation_worker.set_active_geometries(geoms)
        
        # We NO LONGER hide the overlay to prevent flickering/visibility issues
        # Redaction handles removing existing bubbles from the screenshot.

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

    def toggle_overlay_visibility(self, visible):
        """Toggle translation overlay visibility"""
        if visible:
            self.translation_overlay.hide()
            self.status_label.setText("Translations Hidden")
        else:
            self.translation_overlay.show()
            self.status_label.setText("Translations Visible")

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

    def clear_all_translations(self):
        """Clear all translations and reset hashes to force new analysis"""
        self.translation_overlay.clear_translations()
        self.translation_worker.clear_hashes()
        self.status_label.setText("Translations Cleared")

    def toggle_translation(self):
        """Toggle translation process start/stop"""
        if self.translation_worker.running:
            self.stop_translation()
        else:
            self.start_translation()

    def start_translation(self):
        """Start translation process"""
        self.ollama_api.base_url = self.api_url_edit.text()
        self.ollama_api.model = self.api_model_edit.currentText()
        self.ollama_api.num_thread = self.num_thread_spin.value()
        self.ollama_api.num_gpu = self.num_gpu_spin.value()
        self.ollama_api.timeout = self.api_timeout_spin.value()
        self.ollama_api.keep_alive = -1 if self.keep_alive_checkbox.isChecked() else 0
        self.ollama_api.debug = self.debug_mode_checkbox.isChecked()
        
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
            interval=self.interval_spinbox.value(),
            redaction_margin=self.redaction_margin_spin.value()
        )

        # Start translation
        self.translation_worker.clear_hashes()
        self.translation_worker.start_translation()
        self.translation_overlay.show()

        # Update UI
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.tray_toggle_action.setText("Stop Translation")
        self.status_label.setText("Translating...")

        if self.minimize_on_start_checkbox.isChecked():
            self.hide()

    def stop_translation(self):
        """Stop translation process"""
        self.translation_worker.stop_translation()
        self.translation_overlay.hide()

        # Update UI
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.tray_toggle_action.setText("Start Translation")
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
        self.api_model_edit.setCurrentText(self.settings.value("api_model", "qwen3-vl:2b-instruct"))
        self.source_lang_combo.setCurrentText(self.settings.value("source_lang", "auto"))
        self.target_lang_combo.setCurrentText(self.settings.value("target_lang", "English"))
        self.interval_spinbox.setValue(int(self.settings.value("interval", 2000)))
        self.overlay_opacity_slider.setValue(int(self.settings.value("opacity", 80)))
        self.redaction_margin_spin.setValue(int(self.settings.value("redaction_margin", 15)))
        self.debug_mode_checkbox.setChecked(self.settings.value("debug_mode", "false") == "true")
        self.num_thread_spin.setValue(int(self.settings.value("num_thread", 0)))
        self.num_gpu_spin.setValue(int(self.settings.value("num_gpu", 99)))
        self.api_timeout_spin.setValue(int(self.settings.value("api_timeout", 60)))
        self.keep_alive_checkbox.setChecked(self.settings.value("keep_alive", "true") == "true")
        self.minimize_on_start_checkbox.setChecked(self.settings.value("minimize_on_start", "true") == "true")
        
        # Sync API object
        self.ollama_api.base_url = self.api_url_edit.text()
        self.ollama_api.model = self.api_model_edit.currentText()
        self.ollama_api.num_thread = self.num_thread_spin.value()
        self.ollama_api.num_gpu = self.num_gpu_spin.value()
        self.ollama_api.timeout = self.api_timeout_spin.value()
        self.ollama_api.keep_alive = -1 if self.keep_alive_checkbox.isChecked() else 0
        self.ollama_api.debug = self.debug_mode_checkbox.isChecked()
        
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
        self.settings.setValue("redaction_margin", self.redaction_margin_spin.value())
        self.settings.setValue("debug_mode", "true" if self.debug_mode_checkbox.isChecked() else "false")
        self.settings.setValue("num_thread", self.num_thread_spin.value())
        self.settings.setValue("num_gpu", self.num_gpu_spin.value())
        self.settings.setValue("api_timeout", self.api_timeout_spin.value())
        self.settings.setValue("keep_alive", "true" if self.keep_alive_checkbox.isChecked() else "false")
        self.settings.setValue("minimize_on_start", "true" if self.minimize_on_start_checkbox.isChecked() else "false")
        
        # Sync API object
        self.ollama_api.base_url = self.api_url_edit.text()
        self.ollama_api.model = self.api_model_edit.currentText()
        self.ollama_api.num_thread = self.num_thread_spin.value()
        self.ollama_api.num_gpu = self.num_gpu_spin.value()
        self.ollama_api.timeout = self.api_timeout_spin.value()
        self.ollama_api.keep_alive = -1 if self.keep_alive_checkbox.isChecked() else 0
        self.ollama_api.debug = self.debug_mode_checkbox.isChecked()
        
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

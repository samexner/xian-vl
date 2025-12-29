from typing import List
from PyQt6.QtCore import QThread, pyqtSignal, QRect, QPoint, QSize, QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter, QColor
from .models import TranslationMode, TranslationRegion, TranslationResult
from .api import OllamaAPI
from .capture import ScreenCapture

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
        self.redaction_margin = 15 # Default margin for redaction
        self.last_hashes = {}  # Map of region name (or "full") to last hash
        self.active_geometries = []  # Current bubble geometries for redaction

    def set_active_geometries(self, geometries: List[QRect]):
        """Set geometries to be redacted from the capture"""
        self.active_geometries = geometries

    def set_config(self, mode: TranslationMode, regions: List[TranslationRegion],
                   source_lang: str, target_lang: str, interval: int, redaction_margin: int = 15):
        self.mode = mode
        self.regions = regions
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.interval = interval
        self.redaction_margin = redaction_margin

    def start_translation(self):
        self.running = True
        self.start()

    def stop_translation(self):
        """Stop translation process"""
        self.running = False
        self.quit()
        # Non-blocking wait if called from main thread to prevent UI lag
        if QThread.currentThread() == self.thread():
             self.wait(1000) # Short timeout
        else:
             self.wait()

    def clear_hashes(self):
        """Clear the image hashes to force re-translation"""
        self.last_hashes = {}

    def run(self):
        from PyQt6.QtCore import QElapsedTimer
        timer = QElapsedTimer()
        while self.running:
            timer.start()
            try:
                if self.mode == TranslationMode.FULL_SCREEN:
                    self._translate_full_screen()
                else:
                    self._translate_regions()

                # Calculate remaining sleep time to maintain the interval
                elapsed = timer.elapsed()
                remaining = self.interval - elapsed
                
                # Check running flag frequently during sleep to be responsive to 'stop'
                if remaining > 0:
                    for _ in range(int(remaining // 100)):
                        if not self.running: break
                        self.msleep(100)
                    if self.running:
                        self.msleep(int(remaining % 100))
                else:
                    # Give time for GUI thread and prevent flooding
                    self.msleep(100)

            except Exception as e:
                print(f"Translation worker error: {e}")
                # Check running flag during error sleep
                for _ in range(50):
                    if not self.running: break
                    self.msleep(100)
        
        print("Translation worker thread stopped")

    def _redact_image(self, image: QImage, geometries: List[QRect], offset: QPoint = QPoint(0, 0)) -> QImage:
        """Draw black boxes over existing translation areas"""
        if not geometries:
            return image
        
        # Ensure image is in a format we can paint on
        if image.format() == QImage.Format.Format_Invalid:
            return image
            
        redacted = image.copy()
        painter = QPainter(redacted)
        painter.setBrush(QColor(0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        
        for rect in geometries:
            # Adjust rect by offset (for regions, rect is in screen coords)
            adj_rect = rect.translated(-offset)
            # Draw box to ensure text is fully covered
            # Add margin to ensure edge cases are covered (especially scaling/aliasing)
            margin = self.redaction_margin
            adj_rect.adjust(-margin, -margin, margin, margin)
            painter.drawRect(adj_rect)
            
        painter.end()
        
        return redacted

    def _translate_full_screen(self):
        """Handle full screen translation"""
        # We no longer hide/show the overlay for every capture because we use redaction.
        # This prevents flickering and Wayland visibility issues.
        self.request_hide_overlay.emit() # This signal now just updates geometries
        
        # Give GUI thread time to update geometries and process any pending events
        for _ in range(5):
             self.msleep(20)
             if not self.running: return
        
        image_data = ScreenCapture.capture_screen()
        if not self.running: return
        
        if image_data:
            # Load as QImage for redaction
            image = QImage.fromData(image_data)
            if image.isNull():
                print("Error: Captured image is null")
                return
                
            # Redact existing translations
            if self.active_geometries:
                print(f"Redacting {len(self.active_geometries)} bubbles from capture")
            image = self._redact_image(image, self.active_geometries)
            
            # Convert back to bytes for hashing and compression
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.ReadWrite)
            image.save(buffer, "PNG")
            redacted_data = bytes(buffer.buffer())

            # Change detection on REDACTED image
            current_hash = ScreenCapture.calculate_hash(redacted_data)
            if self.last_hashes.get("full") == current_hash:
                # No change, skip API
                return
            
            # Get original size for scaling back
            orig_size = image.size()
            
            # Compress image before sending to API (50% quality)
            compressed_data, scaled_w, scaled_h = ScreenCapture.compress_image(redacted_data, quality=50)
            scaled_size = QSize(scaled_w, scaled_h)
            
            print(f"Sending full screen to API ({orig_size.width()}x{orig_size.height()})")
            results = self.ollama_api.translate_image(
                compressed_data, self.source_lang, self.target_lang, self.mode,
                original_size=orig_size, scaled_size=scaled_size
            )
            
            if not self.running: return

            # Update hash ONLY after a successful API call attempt
            self.last_hashes["full"] = current_hash
            
            if results:
                self.translation_ready.emit(results)
            else:
                print("API returned no new translations")
        else:
            print("Error: Failed to capture screen")

    def _translate_regions(self):
        """Handle region-based translation"""
        self.request_hide_overlay.emit()
        for _ in range(5):
             self.msleep(20)
             if not self.running: return
        
        # Capture all regions first
        captured_images = []
        for region in self.regions:
            if not self.running: break
            if not region.enabled:
                continue
            
            image_data = ScreenCapture.capture_region(
                region.x, region.y, region.width, region.height
            )
            if not self.running: break
            if image_data:
                # Load as QImage for redaction
                image = QImage.fromData(image_data)
                if image.isNull():
                    continue
                
                # Redact existing translations in this region
                # Bubble geometries are in screen coordinates
                region_rect = QRect(region.x, region.y, region.width, region.height)
                # Filter geometries that intersect this region
                intersecting = [g for g in self.active_geometries if region_rect.intersects(g)]
                image = self._redact_image(image, intersecting, offset=QPoint(region.x, region.y))
                
                # Convert back to bytes
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.ReadWrite)
                image.save(buffer, "PNG")
                redacted_data = bytes(buffer.buffer())

                # Change detection per region on REDACTED image
                current_hash = ScreenCapture.calculate_hash(redacted_data)
                region_key = f"region_{region.x}_{region.y}_{region.width}_{region.height}"
                if self.last_hashes.get(region_key) == current_hash:
                    continue
                
                captured_images.append((region, redacted_data, current_hash, region_key))
        
        if not self.running: return
        
        if not captured_images:
            return

        all_results = []
        for region, image_data, current_hash, region_key in captured_images:
            if not self.running: break
            original_image = QImage.fromData(image_data)
            orig_size = original_image.size()
            
            # Compress image before sending to API (50% quality)
            compressed_data, scaled_w, scaled_h = ScreenCapture.compress_image(image_data, quality=50)
            scaled_size = QSize(scaled_w, scaled_h)
            
            print(f"Sending region '{region.name}' to API ({orig_size.width()}x{orig_size.height()})")
            results = self.ollama_api.translate_image(
                compressed_data, self.source_lang, self.target_lang, TranslationMode.REGION_SELECT,
                original_size=orig_size, scaled_size=scaled_size
            )
            
            if not self.running: break

            # Update hash after API call
            self.last_hashes[region_key] = current_hash

            # Adjust coordinates for region
            if results:
                print(f"Region '{region.name}' returned {len(results)} results")
                for result in results:
                    result.x += region.x
                    result.y += region.y
                    all_results.append(result)
            else:
                print(f"Region '{region.name}' returned no new translations")

        if all_results and self.running:
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

from typing import List
from PyQt6.QtCore import QThread, pyqtSignal, QRect, QPoint, QSize, QBuffer, QIODevice, Qt, QThreadPool, QRunnable
from PyQt6.QtGui import QImage, QPainter, QColor, QCursor, QGuiApplication
from .models import TranslationMode, TranslationRegion, TranslationResult
from .api import TransformersTranslator
from .capture import ScreenCapture

try:
    import easyocr
except ImportError:
    easyocr = None

class TranslationWorker(QThread):
    """Worker thread for handling translations"""

    translation_ready = pyqtSignal(list, object) # list of results, optional QRect of the updated area
    status_update = pyqtSignal(str) # Status message for the UI
    request_hide_overlay = pyqtSignal()
    request_show_overlay = pyqtSignal()

    def __init__(self, translator: TransformersTranslator):
        super().__init__()
        self.translator = translator
        self.running = False
        self.mode = TranslationMode.FULL_SCREEN
        self.regions = []
        self.source_lang = "auto"
        self.target_lang = "English"
        self.interval = 2000  # ms
        self.redaction_margin = 15 # Default margin for redaction
        self.last_hashes = {}  # Map of region key or "full" to last hash
        self.active_geometries = []  # Current bubble geometries for redaction
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(4) # Sane number of threads
        self.ocr_reader = None
        self._init_ocr()

    def _init_ocr(self):
        """Initialize EasyOCR reader"""
        if easyocr and not self.ocr_reader:
            try:
                # Initialize with English and Chinese/Japanese/Korean as common game languages
                # In a real app we might want to configure this
                print("Initializing EasyOCR...")
                self.ocr_reader = easyocr.Reader(['en', 'ch_sim', 'ja', 'ko'])
                print("EasyOCR initialized")
            except Exception as e:
                print(f"Failed to initialize EasyOCR: {e}")

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
        self.thread_pool.clear() # Cancel pending tasks
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
            # Request latest geometries for redaction
            self.request_hide_overlay.emit()
            
            try:
                # Use EasyOCR for all modes as requested
                self._translate_with_ocr()

                # Calculate remaining sleep time
                elapsed = timer.elapsed()
                # Use 1 second interval as requested
                target_interval = 1000
                remaining = target_interval - elapsed
                
                if remaining > 0:
                    self.msleep(int(remaining))
                else:
                    self.msleep(1) # Minimal sleep to prevent CPU hogging

            except Exception as e:
                print(f"Translation worker error: {e}")
                self.msleep(1000)
        
        print("Translation worker thread stopped")

    def _translate_with_ocr(self):
        """Capture screen, perform OCR with EasyOCR, and translate via Transformers"""
        if not self.ocr_reader:
            self.status_update.emit("EasyOCR not available")
            return

        self.status_update.emit("Capturing screen...")
        image_data = ScreenCapture.capture_screen()
        if not image_data or not self.running:
            return

        # Redact existing translations to avoid OCR-ing them
        if self.active_geometries:
            image = QImage.fromData(image_data)
            if not image.isNull():
                image = self._redact_image(image, self.active_geometries)
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                image_data = bytes(buffer.buffer())

        # Use image hash to avoid redundant OCR if nothing changed
        image_hash = ScreenCapture.calculate_hash(image_data)
        if image_hash == self.last_hashes.get("full"):
            return
        self.last_hashes["full"] = image_hash

        self.status_update.emit("Performing OCR...")
        try:
            # EasyOCR can take bytes
            results = self.ocr_reader.readtext(image_data)
            
            if not results:
                self.status_update.emit("No text detected")
                self.translation_ready.emit([], None)
                return

            # Format results for translation
            ocr_regions = []
            for (bbox, text, prob) in results:
                if prob < 0.2: continue # Filter low confidence
                
                # bbox is [[x0, y0], [x1, y1], [x2, y2], [x3, y3]]
                x = min(p[0] for p in bbox)
                y = min(p[1] for p in bbox)
                w = max(p[0] for p in bbox) - x
                h = max(p[1] for p in bbox) - y
                
                ocr_regions.append({
                    "text": text,
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h
                })

            if not ocr_regions:
                self.translation_ready.emit([], None)
                return

            self.status_update.emit(f"Translating {len(ocr_regions)} regions...")
            translated_results = self.translator.translate_text_regions(
                ocr_regions, self.source_lang, self.target_lang
            )
            
            if translated_results:
                self.translation_ready.emit(translated_results, None)
                self.status_update.emit("Translation complete")
            else:
                self.status_update.emit("Translation failed")

        except Exception as e:
            print(f"OCR translation error: {e}")
            self.status_update.emit(f"OCR Error: {e}")

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
            margin = self.redaction_margin
            adj_rect.adjust(-margin, -margin, margin, margin)
            painter.drawRect(adj_rect)
            
        painter.end()
        return redacted

class TranslatorStatusWorker(QThread):
    """Worker thread for checking translator status and fetching models"""
    status_changed = pyqtSignal(bool, list)

    def __init__(self, translator: TransformersTranslator):
        super().__init__()
        self.translator = translator

    def run(self):
        is_available = self.translator.is_available()
        models = []
        if is_available:
            models = self.translator.get_available_models()
        self.status_changed.emit(is_available, models)

from typing import List
import time
import logging
from collections import OrderedDict
from PyQt6.QtCore import QThread, pyqtSignal, QRect, QPoint, QSize, QBuffer, QIODevice, Qt, QThreadPool, QRunnable
from PyQt6.QtGui import QImage, QPainter, QColor, QCursor, QGuiApplication
from .models import TranslationMode, TranslationRegion, TranslationResult
from .translation_service import TransformersTranslator
from .screen_capture import ScreenCapture

logger = logging.getLogger(__name__)

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
        # Caches to reduce refresh churn
        self.image_cache = OrderedDict()  # image_hash -> {"ocr": list, "translations": list}
        self.image_cache_max = 8
        self.ocr_translation_cache = OrderedDict()  # fingerprint -> translations
        self.translation_cache_max = 16
        self._last_translation_signature = None
        self._empty_signature = ("__empty__",)
        self._init_ocr()

    def _init_ocr(self):
        """Initialize EasyOCR reader with current language configuration"""
        if not easyocr:
            return

        # Map UI language names to EasyOCR codes
        lang_map = {
            "Japanese": ["ja", "en"],
            "Korean": ["ko", "en"],
            "Chinese": ["ch_sim", "en"],
            "Spanish": ["es", "en"],
            "French": ["fr", "en"],
            "English": ["en"],
            "auto": ["en", "ch_sim"] # Default to English + Simplified Chinese if auto
        }

        target_langs = lang_map.get(self.source_lang, ["en"])

        # Check if we need to re-initialize
        if self.ocr_reader and getattr(self, '_current_ocr_langs', []) == target_langs:
            return

        try:
            logger.info(f"Initializing EasyOCR with {target_langs}...")
            start_time = time.time()
            self.ocr_reader = easyocr.Reader(target_langs)
            self._current_ocr_langs = target_langs
            logger.info(f"EasyOCR initialized in {time.time() - start_time:.2f}s")
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")
            self.status_update.emit(f"OCR Init Error: {e}")

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
        
        # Re-initialize OCR if language changed
        self._init_ocr()

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
        """Clear the image hashes and translation cache to force re-translation"""
        self.last_hashes = {}
        self.image_cache.clear()
        self.ocr_translation_cache.clear()
        self._last_translation_signature = None
        if hasattr(self.translator, 'cache'):
            try:
                self.translator.cache.clear()
            except Exception:
                self.translator.cache = OrderedDict()

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
                logger.error(f"Translation worker error: {e}")
                self.msleep(1000)
        
        logger.info("Translation worker thread stopped")

    def _translate_with_ocr(self):
        """Capture screen, perform OCR with EasyOCR, and translate via Transformers"""
        workflow_start = time.time()
        if not self.ocr_reader:
            self.status_update.emit("EasyOCR not available")
            return

        self.status_update.emit("Capturing screen...")
        capture_start = time.time()
        image_data = ScreenCapture.capture_screen()
        if not image_data or not self.running:
            return
        capture_time = time.time() - capture_start

        # Redact existing translations to avoid OCR-ing them
        redact_time = 0
        if self.active_geometries:
            redact_start = time.time()
            image = QImage.fromData(image_data)
            if not image.isNull():
                # Geometries are in global screen coordinates.
                # Capture is assumed to be the full virtual desktop.
                capture_geo = ScreenCapture.get_virtual_desktop_geometry()
                image = self._redact_image(image, self.active_geometries, capture_geo.topLeft())
                
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                image_data = bytes(buffer.buffer())
            redact_time = time.time() - redact_start

        # Preprocess image for better OCR results
        preprocess_start = time.time()
        image_data = ScreenCapture.preprocess_image(image_data)
        preprocess_time = time.time() - preprocess_start

        # Use image hash to avoid redundant OCR if nothing changed
        hash_start = time.time()
        image_hash = ScreenCapture.calculate_hash(image_data)
        hash_time = time.time() - hash_start
        cached_entry = self.image_cache.get(image_hash)

        if cached_entry and cached_entry.get("translations"):
            logger.debug("Image cache hit with translations; reusing previous results")
            self.last_hashes["full"] = image_hash
            signature = self._fingerprint_translations(cached_entry["translations"])
            if signature == self._last_translation_signature:
                logger.debug("Translation signature unchanged; suppressing overlay refresh")
                return
            self._last_translation_signature = signature
            self.translation_ready.emit(cached_entry["translations"], None)
            self.status_update.emit("Using cached translations")
            return

        if image_hash == self.last_hashes.get("full"):
            logger.debug("Image hash unchanged, skipping OCR")
            return
        self.last_hashes["full"] = image_hash

        ocr_regions = None
        ocr_time = 0.0

        if cached_entry and cached_entry.get("ocr") is not None:
            logger.debug("Image cache hit for OCR; skipping OCR step")
            ocr_regions = cached_entry.get("ocr")
        else:
            self.status_update.emit("Performing OCR...")
            ocr_start = time.time()
            try:
                # EasyOCR can take bytes
                results = self.ocr_reader.readtext(image_data)
                ocr_time = time.time() - ocr_start
                
                if not results:
                    logger.info(f"OCR finished in {ocr_time:.2f}s: No text detected")
                    self.status_update.emit("No text detected")

                    # Keep existing translations on screen; just record the empty state
                    # to suppress redundant refreshes until something changes.
                    self._store_image_cache(image_hash, ocr_regions=[])
                    self._last_translation_signature = self._empty_signature
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

                logger.info(f"OCR detected {len(results)} regions, {len(ocr_regions)} kept after filtering in {ocr_time:.2f}s")
                self._store_image_cache(image_hash, ocr_regions=ocr_regions)

                if not ocr_regions:
                    # Maintain current overlay; just record the empty state.
                    self._last_translation_signature = self._empty_signature
                    return
            except Exception as e:
                logger.error(f"OCR translation error: {e}")
                self.status_update.emit(f"OCR Error: {e}")
                return

        if ocr_regions is None:
            logger.info("No OCR regions available after cache/OCR stage")
            return

        # Attempt translation reuse based on OCR fingerprint
        ocr_signature = self._fingerprint_ocr_regions(ocr_regions)
        cached_translations = self.ocr_translation_cache.get(ocr_signature)
        if cached_translations:
            logger.debug("OCR signature cache hit; reusing translations")
            self._store_image_cache(image_hash, ocr_regions=ocr_regions, translations=cached_translations)
            signature = self._fingerprint_translations(cached_translations)
            if signature == self._last_translation_signature:
                logger.debug("Translation signature unchanged; suppressing overlay refresh")
                return
            self._last_translation_signature = signature
            self.translation_ready.emit(cached_translations, None)
            self.status_update.emit("Using cached translations")
            return

        self.status_update.emit(f"Translating {len(ocr_regions)} regions...")
        translate_start = time.time()
        translated_results = self.translator.translate_text_regions(
            ocr_regions, self.source_lang, self.target_lang
        )
        translate_time = time.time() - translate_start
        
        workflow_total = time.time() - workflow_start
        logger.info(f"Workflow stats: Capture: {capture_time:.2f}s, Redact: {redact_time:.2f}s, "
                    f"Preprocess: {preprocess_time:.2f}s, Hash: {hash_time:.2f}s, "
                    f"OCR: {ocr_time:.2f}s, Translate: {translate_time:.2f}s, Total: {workflow_total:.2f}s")

        if translated_results:
            self._store_image_cache(image_hash, ocr_regions=ocr_regions, translations=translated_results)
            self._store_translation_signature(ocr_signature, translated_results)

            signature = self._fingerprint_translations(translated_results)
            if signature == self._last_translation_signature:
                logger.debug("Translation signature unchanged after translate; suppressing overlay refresh")
                return
            self._last_translation_signature = signature

            self.translation_ready.emit(translated_results, None)
            self.status_update.emit("Translation complete")
        else:
            self.status_update.emit("Translation failed")

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

    def _store_image_cache(self, image_hash: str, ocr_regions=None, translations=None):
        entry = self.image_cache.get(image_hash, {})
        if ocr_regions is not None:
            # store a shallow copy to avoid accidental mutation
            entry["ocr"] = [dict(r) for r in ocr_regions]
        if translations is not None:
            entry["translations"] = translations
        self.image_cache[image_hash] = entry
        try:
            self.image_cache.move_to_end(image_hash)
        except Exception:
            pass
        evicted = []
        while len(self.image_cache) > self.image_cache_max:
            try:
                k, _ = self.image_cache.popitem(last=False)
                evicted.append(k)
            except Exception:
                break

        if evicted:
            logger.debug("Image cache evicted %d item(s); max=%d", len(evicted), self.image_cache_max)
        else:
            # Log what was stored to aid debugging of reuse paths
            logger.debug(
                "Image cache stored hash=%s (ocr=%s, translations=%s, size=%d/%d)",
                image_hash,
                "yes" if ocr_regions is not None else "no",
                "yes" if translations is not None else "no",
                len(self.image_cache),
                self.image_cache_max,
            )

    def _store_translation_signature(self, signature, translations):
        self.ocr_translation_cache[signature] = translations
        try:
            self.ocr_translation_cache.move_to_end(signature)
        except Exception:
            pass
        evicted = []
        while len(self.ocr_translation_cache) > self.translation_cache_max:
            try:
                k, _ = self.ocr_translation_cache.popitem(last=False)
                evicted.append(k)
            except Exception:
                break

        if evicted:
            logger.debug("OCR signature cache evicted %d item(s); max=%d", len(evicted), self.translation_cache_max)
        else:
            logger.debug(
                "OCR signature cache stored signature with %d translations (size=%d/%d)",
                len(translations) if translations is not None else 0,
                len(self.ocr_translation_cache),
                self.translation_cache_max,
            )

    def _fingerprint_ocr_regions(self, ocr_regions):
        try:
            return tuple(sorted(
                (
                    int(round(r.get("x", 0))),
                    int(round(r.get("y", 0))),
                    int(round(r.get("width", 0))),
                    int(round(r.get("height", 0))),
                    r.get("text", "").strip()
                )
                for r in ocr_regions
            ))
        except Exception:
            return tuple()

    def _fingerprint_translations(self, translations: List[TranslationResult]):
        try:
            return tuple(sorted(
                (
                    int(round(t.x)),
                    int(round(t.y)),
                    int(round(t.width)),
                    int(round(t.height)),
                    t.translated_text.strip()
                )
                for t in translations
            ))
        except Exception:
            return tuple()

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


class ModelWarmupWorker(QThread):
    """Worker thread to preload the transformers model/tokenizer before translation starts."""

    warmup_finished = pyqtSignal(bool, str)

    def __init__(self, translator: TransformersTranslator):
        super().__init__()
        self.translator = translator

    def run(self):
        try:
            ok = self.translator.ensure_loaded()
            err = "" if ok else (getattr(self.translator, "last_error", "") or "Model warmup failed")
            self.warmup_finished.emit(ok, err)
        except Exception as e:
            logger.error(f"Model warmup error: {e}")
            self.warmup_finished.emit(False, str(e))

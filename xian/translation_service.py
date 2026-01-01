import torch
import time
import logging
from collections import OrderedDict
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from typing import List
from .models import TranslationResult

logger = logging.getLogger(__name__)

class TransformersTranslator:
    """Interface to local Transformers NLLB model"""

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-600M"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self._loaded_model_name = None
        self.lang_map = {
            "Japanese": "jpn_Jpan",
            "Korean": "kor_Kore",
            "Chinese": "zho_Hans",
            "Spanish": "spa_Latn",
            "French": "fra_Latn",
            "English": "eng_Latn",
            "auto": "auto"
        }
        self.cache = OrderedDict()
        self.cache_max_items = 500

    def _cache_get(self, key):
        val = self.cache.get(key)
        if val is not None:
            # Move to end to mark as recently used
            try:
                self.cache.move_to_end(key)
            except Exception:
                pass
        return val

    def _cache_set(self, key, value):
        self.cache[key] = value
        try:
            self.cache.move_to_end(key)
        except Exception:
            pass

        evicted_keys = []
        while len(self.cache) > self.cache_max_items:
            try:
                evicted_key, _ = self.cache.popitem(last=False)
                evicted_keys.append(evicted_key)
            except Exception:
                break

        if evicted_keys:
            try:
                logger.debug("Translation cache evicted %d item(s); max=%d", len(evicted_keys), self.cache_max_items)
            except Exception:
                pass
        else:
            try:
                logger.debug("Translation cache stored key=%s (size=%d/%d)", key, len(self.cache), self.cache_max_items)
            except Exception:
                pass

    def ensure_loaded(self) -> bool:
        """Eagerly load model/tokenizer (for warmup before starting translation)."""
        self._load_model()
        return self.model is not None and self.tokenizer is not None

    def _load_model(self):
        """Lazy load the model and tokenizer"""
        if self.model is not None and self._loaded_model_name == self.model_name:
            return

        if self.model is not None and self._loaded_model_name != self.model_name:
            logger.info(
                "Model name changed (%s -> %s); reloading model/tokenizer...",
                self._loaded_model_name,
                self.model_name,
            )
            self.model = None
            self.tokenizer = None

        if self.model is None:
            logger.info(f"Loading model {self.model_name} on {self.device}...")
            start_time = time.time()
            try:
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name).to(self.device)
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._loaded_model_name = self.model_name
                logger.info(f"Model loaded successfully in {time.time() - start_time:.2f}s")
            except Exception as e:
                self.model = None
                self.tokenizer = None
                self._loaded_model_name = None
                logger.error(f"Error loading model: {e}")

    def _resolve_forced_bos_token_id(self, tgt_lang_code: str):
        """Resolve NLLB target language ID across tokenizer variants/versions."""
        tok = self.tokenizer
        if tok is None:
            return None

        # Newer/variant tokenizers may expose a helper
        get_lang_id = getattr(tok, "get_lang_id", None)
        if callable(get_lang_id):
            try:
                return int(get_lang_id(tgt_lang_code))
            except Exception:
                pass

        # Older tokenizers may expose a mapping
        lang_code_to_id = getattr(tok, "lang_code_to_id", None)
        if isinstance(lang_code_to_id, dict) and tgt_lang_code in lang_code_to_id:
            try:
                return int(lang_code_to_id[tgt_lang_code])
            except Exception:
                pass

        # Fallback: language codes are tokens in NLLB vocab
        convert_tokens_to_ids = getattr(tok, "convert_tokens_to_ids", None)
        if callable(convert_tokens_to_ids):
            try:
                token_id = convert_tokens_to_ids(tgt_lang_code)
                if isinstance(token_id, int):
                    if getattr(tok, "unk_token_id", None) is not None and token_id == tok.unk_token_id:
                        return None
                    return int(token_id)
            except Exception:
                pass

        return None

    def is_available(self) -> bool:
        """Check if transformers backend is ready"""
        return True

    def get_available_models(self) -> List[str]:
        """Return the currently configured model"""
        return [self.model_name, "facebook/nllb-200-distilled-1.3B", "facebook/nllb-200-3.3B"]

    def translate_text_regions(self, regions: List[dict], source_lang: str = "auto",
                               target_lang: str = "English") -> List[TranslationResult]:
        """Translate OCR'd text regions using NLLB with batching and caching"""
        self._load_model()
        if self.model is None or self.tokenizer is None:
            return []
        
        tgt_lang_code = self.lang_map.get(target_lang, "eng_Latn")
        src_lang_code = self.lang_map.get(source_lang) if source_lang != "auto" else None
        
        results = []
        to_translate = []
        to_translate_indices = []
        
        for i, region in enumerate(regions):
            text = region.get("text", "").strip()
            if not text:
                continue
                
            # Check cache
            cache_key = (self.model_name, text, source_lang, target_lang)
            cached_value = self._cache_get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for: {text[:30]}...")
                results.append(TranslationResult(
                    translated_text=cached_value,
                    x=float(region.get('x', 0)),
                    y=float(region.get('y', 0)),
                    width=float(region.get('width', 0)),
                    height=float(region.get('height', 0))
                ))
            else:
                logger.debug(f"Cache miss for: {text[:30]}...")
                to_translate.append(text)
                to_translate_indices.append(i)
                # Placeholder for result to maintain order if we cared, 
                # but we'll just append at the end for now as original code did.
                # Actually, original code appends in loop, so order is same as regions.
                # To maintain order and handle mixing cached/non-cached, let's use a list of None.
                results.append(None)

        if to_translate:
            logger.info(f"Translating batch of {len(to_translate)} items...")
            for i, text in enumerate(to_translate):
                logger.debug(f"  [{i}] OCR text: {text}")
            batch_start = time.time()
            try:
                if src_lang_code and hasattr(self.tokenizer, "src_lang"):
                    self.tokenizer.src_lang = src_lang_code

                forced_bos_token_id = self._resolve_forced_bos_token_id(tgt_lang_code)
                if forced_bos_token_id is None:
                    logger.error(
                        "Unable to resolve target language token id for %s (tgt_lang_code=%s, tokenizer=%s)",
                        target_lang,
                        tgt_lang_code,
                        type(self.tokenizer).__name__,
                    )
                    return []

                # Batch tokenize
                inputs = self.tokenizer(to_translate, return_tensors="pt", padding=True).to(self.device)
                
                # Batch generate
                translated_tokens = self.model.generate(
                    **inputs, 
                    forced_bos_token_id=forced_bos_token_id,
                    max_length=128
                )
                
                # Batch decode
                translated_texts = self.tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)
                logger.info(f"Batch translation completed in {time.time() - batch_start:.2f}s")
                
                # Update cache and results
                for idx, text, translated_text in zip(to_translate_indices, to_translate, translated_texts):
                    cache_key = (self.model_name, text, source_lang, target_lang)
                    self._cache_set(cache_key, translated_text)
                    
                    region = regions[idx]
                    results[idx] = TranslationResult(
                        translated_text=translated_text,
                        x=float(region.get('x', 0)),
                        y=float(region.get('y', 0)),
                        width=float(region.get('width', 0)),
                        height=float(region.get('height', 0))
                    )
            except Exception as e:
                logger.error(f"Batch translation error: {e}")
                
        # Filter out None and empty results
        return [r for r in results if r is not None]



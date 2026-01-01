import torch
import time
import logging
from collections import OrderedDict
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from typing import List
from .models import TranslationResult

logger = logging.getLogger(__name__)

class TransformersTranslator:
    """Interface to local Transformers model(s): NLLB, M2M100, and Marian (Helsinki opus-mt)."""

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-600M"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self._loaded_model_name = None
        # Optional hints used for preloading when Marian generic selector is chosen
        self.hint_source_lang: str | None = None
        self.hint_target_lang: str | None = None
        # Last error detail (for UI)
        self.last_error: str | None = None
        # Language codes for NLLB
        self.lang_map_nllb = {
            "Japanese": "jpn_Jpan",
            "Korean": "kor_Kore",
            "Chinese": "zho_Hans",
            "Spanish": "spa_Latn",
            "French": "fra_Latn",
            "English": "eng_Latn",
            "auto": "auto"
        }
        # Language codes for M2M100 (418M)
        self.lang_map_m2m = {
            "Japanese": "ja",
            "Korean": "ko",
            "Chinese": "zh",
            "Spanish": "es",
            "French": "fr",
            "English": "en",
            "auto": None,
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
        self.last_error = None
        family = self._detect_family()
        try:
            logger.debug("ensure_loaded: family=%s, model_name=%s, hints=(%s -> %s)",
                         family, self.model_name, self.hint_source_lang, self.hint_target_lang)
        except Exception:
            pass
        # Special handling: Marian generic selector needs explicit direction at warmup
        if family == "marian" and (self.model_name or "").lower() == "helsinki-nlp/opus-mt":
            src = (self.hint_source_lang or "").strip()
            tgt = (self.hint_target_lang or "").strip()
            chosen = self._resolve_marian_model_for_pair(src, tgt)
            if not chosen:
                self.last_error = (
                    "Helsinki-NLP/opus-mt requires explicit Source and Target (e.g., Japanese → English). "
                    "Set Source/Target in settings; 'auto' is not supported for opus-mt."
                )
                logger.error(self.last_error + f" (got: {src or 'auto'} -> {tgt or 'auto'})")
                return False
            try:
                logger.info("Preparing Marian opus-mt pair %s -> %s; resolving to %s", src, tgt, chosen)
            except Exception:
                pass
            self._load_specific_model(chosen)
            return self.model is not None and self.tokenizer is not None

        # Default behavior for NLLB and M2M100 and specific Marian names
        self._load_model()
        ok = self.model is not None and self.tokenizer is not None
        if not ok and not self.last_error:
            self.last_error = "Failed to load model. Check model name and environment."
        return ok

    def _detect_family(self, name: str = None) -> str:
        """Return model family: 'nllb', 'm2m100', or 'marian'."""
        nm = (name or self.model_name or "").lower()
        if nm.startswith("facebook/m2m100_418m") or nm.endswith("m2m100_418m"):
            return "m2m100"
        if nm.startswith("helsinki-nlp/opus-mt"):
            return "marian"
        # default to NLLB for backward-compat
        return "nllb"

    def _resolve_marian_model_for_pair(self, source_lang: str, target_lang: str) -> str | None:
        """Pick a Marian opus-mt checkpoint for the language pair.
        Currently supports JP/KO/ZH <-> EN common directions.
        """
        # Normalize various user-visible language variants and cases
        def _normalize_lang(name: str) -> str | None:
            if not name:
                return None
            n = name.strip().lower()
            aliases = {
                # English
                "english": "English", "en": "English", "eng": "English",
                # Japanese
                "japanese": "Japanese", "ja": "Japanese", "jp": "Japanese", "jpn": "Japanese", "日本語": "Japanese",
                # Korean
                "korean": "Korean", "ko": "Korean", "kr": "Korean", "kor": "Korean", "한국어": "Korean",
                # Chinese (treat all as generic Chinese for Marian pair selection)
                "chinese": "Chinese", "zh": "Chinese", "zho": "Chinese", "cn": "Chinese",
                "zh-cn": "Chinese", "zh_cn": "Chinese",
                "zh-hans": "Chinese", "zh_hans": "Chinese", "简体中文": "Chinese", "中文": "Chinese",
                "zh-hant": "Chinese", "zh_hant": "Chinese", "繁體中文": "Chinese",
                # Auto (unsupported for Marian generic resolution)
                "auto": None,
            }
            return aliases.get(n, None)

        src = _normalize_lang(source_lang)
        tgt = _normalize_lang(target_lang)
        if not src or not tgt:
            return None
        # At this point, src/tgt are canonical labels used below
        pair = (src, tgt)
        mapping = {
            ("Japanese", "English"): "Helsinki-NLP/opus-mt-ja-en",
            ("English", "Japanese"): "Helsinki-NLP/opus-mt-en-ja",
            ("Korean", "English"): "Helsinki-NLP/opus-mt-ko-en",
            ("English", "Korean"): "Helsinki-NLP/opus-mt-en-ko",
            ("Chinese", "English"): "Helsinki-NLP/opus-mt-zh-en",
            ("English", "Chinese"): "Helsinki-NLP/opus-mt-en-zh",
        }
        return mapping.get(pair)

    def _load_specific_model(self, model_name: str):
        """Load a specific HF model+tokenizer name on the configured device."""
        if self.model is not None and self._loaded_model_name == model_name:
            return
        # Reset if different
        if self._loaded_model_name and self._loaded_model_name != model_name:
            try:
                logger.info("Unloading model %s", self._loaded_model_name)
            except Exception:
                pass
            self.model = None
            self.tokenizer = None
            self._loaded_model_name = None

        logger.info(f"Loading model {model_name} on {self.device}...")
        start_time = time.time()
        try:
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(self.device)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._loaded_model_name = model_name
            logger.info(f"Model loaded successfully in {time.time() - start_time:.2f}s")
        except Exception as e:
            self.model = None
            self.tokenizer = None
            self._loaded_model_name = None
            logger.error(f"Error loading model: {e}")
            self.last_error = str(e)

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

        # For Marian generic entry, defer to translate phase where we know the pair
        family = self._detect_family()
        if family == "marian" and self.model_name.lower() == "helsinki-nlp/opus-mt":
            return

        if self.model is None:
            self._load_specific_model(self.model_name)

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
        """Return suggested models to pick from"""
        # Put current model first, then common options
        models = OrderedDict()
        models[self.model_name] = True
        models["facebook/nllb-200-distilled-600M"] = True
        models["facebook/m2m100_418M"] = True
        # Generic Marian selector (direction resolved at runtime)
        models["Helsinki-NLP/opus-mt"] = True
        return list(models.keys())

    def translate_text_regions(self, regions: List[dict], source_lang: str = "auto",
                               target_lang: str = "English") -> List[TranslationResult]:
        """Translate OCR'd text regions with batching and caching across families."""
        family = self._detect_family()
        # For Marian generic name, pick a specific checkpoint using src/tgt
        effective_model_name = self.model_name
        if family == "marian" and self.model_name.lower() == "helsinki-nlp/opus-mt":
            chosen = self._resolve_marian_model_for_pair(source_lang, target_lang)
            if not chosen:
                logger.error("Marian (opus-mt) requires explicit source/target pair (got %s -> %s)", source_lang, target_lang)
                return []
            effective_model_name = chosen
        
        # Ensure a suitable model is loaded
        if self._loaded_model_name != effective_model_name or self.model is None or self.tokenizer is None:
            self._load_specific_model(effective_model_name)
        if self.model is None or self.tokenizer is None:
            return []

        # Resolve language codes per family
        if family == "nllb":
            tgt_lang_code = self.lang_map_nllb.get(target_lang, "eng_Latn")
            src_lang_code = self.lang_map_nllb.get(source_lang) if source_lang != "auto" else None
        elif family == "m2m100":
            tgt_lang_code = self.lang_map_m2m.get(target_lang, "en")
            src_lang_code = self.lang_map_m2m.get(source_lang) if source_lang != "auto" else None
        else:  # marian: handled by model selection; no lang codes
            tgt_lang_code = None
            src_lang_code = None
        
        results = []
        to_translate = []
        to_translate_indices = []
        
        for i, region in enumerate(regions):
            text = region.get("text", "").strip()
            if not text:
                continue
                
            # Check cache
            cache_key = (effective_model_name, text, source_lang, target_lang)
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
                # Family-specific pre-encode settings
                if src_lang_code and hasattr(self.tokenizer, "src_lang"):
                    self.tokenizer.src_lang = src_lang_code
                
                # Batch tokenize
                inputs = self.tokenizer(to_translate, return_tensors="pt", padding=True).to(self.device)
                
                # Batch generate: branch per family
                gen_kwargs = {"max_length": 128}
                if family in ("nllb", "m2m100"):
                    forced_bos_token_id = self._resolve_forced_bos_token_id(tgt_lang_code)
                    if forced_bos_token_id is None:
                        logger.error(
                            "Unable to resolve target language token id for %s (tgt_lang_code=%s, tokenizer=%s)",
                            target_lang,
                            tgt_lang_code,
                            type(self.tokenizer).__name__,
                        )
                        return []
                    gen_kwargs["forced_bos_token_id"] = forced_bos_token_id

                translated_tokens = self.model.generate(
                    **inputs,
                    **gen_kwargs,
                )
                
                # Batch decode
                translated_texts = self.tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)
                logger.info(f"Batch translation completed in {time.time() - batch_start:.2f}s")
                
                # Update cache and results
                for idx, text, translated_text in zip(to_translate_indices, to_translate, translated_texts):
                    cache_key = (effective_model_name, text, source_lang, target_lang)
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



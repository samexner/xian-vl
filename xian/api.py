import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from typing import List
from .models import TranslationResult

class TransformersTranslator:
    """Interface to local Transformers NLLB model"""

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-600M"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self.lang_map = {
            "Japanese": "jpn_Jpan",
            "Korean": "kor_Kore",
            "Chinese": "zho_Hans",
            "Spanish": "spa_Latn",
            "French": "fra_Latn",
            "English": "eng_Latn",
            "auto": "auto"
        }

    def _load_model(self):
        """Lazy load the model and tokenizer"""
        if self.model is None:
            print(f"Loading model {self.model_name} on {self.device}...")
            try:
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name).to(self.device)
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                print("Model loaded successfully.")
            except Exception as e:
                print(f"Error loading model: {e}")

    def is_available(self) -> bool:
        """Check if transformers backend is ready"""
        return True

    def get_available_models(self) -> List[str]:
        """Return the currently configured model"""
        return [self.model_name, "facebook/nllb-200-distilled-1.3B", "facebook/nllb-200-3.3B"]

    def translate_text_regions(self, regions: List[dict], source_lang: str = "auto",
                               target_lang: str = "English") -> List[TranslationResult]:
        """Translate OCR'd text regions using NLLB"""
        self._load_model()
        if self.model is None:
            return []
        
        tgt_lang_code = self.lang_map.get(target_lang, "eng_Latn")
        
        results = []
        for region in regions:
            text = region.get("text", "")
            if not text.strip():
                continue
                
            try:
                if source_lang != "auto":
                    src_lang_code = self.lang_map.get(source_lang)
                    if src_lang_code:
                        self.tokenizer.src_lang = src_lang_code

                inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
                
                translated_tokens = self.model.generate(
                    **inputs, 
                    forced_bos_token_id=self.tokenizer.lang_code_to_id[tgt_lang_code],
                    max_length=128
                )
                translated_text = self.tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]
                
                results.append(TranslationResult(
                    translated_text=translated_text,
                    x=float(region.get('x', 0)),
                    y=float(region.get('y', 0)),
                    width=float(region.get('width', 0)),
                    height=float(region.get('height', 0))
                ))
            except Exception as e:
                print(f"Translation error for '{text}': {e}")
                
        return results



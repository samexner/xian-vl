import json
import base64
import requests
import re
from typing import List
from PyQt6.QtCore import QSize
from .models import TranslationMode, TranslationResult

class OllamaAPI:
    """Interface to local Ollama Qwen3-VL API"""

    def __init__(self, base_url: str = "http://192.168.0.162:11434"):
        self.base_url = base_url
        self.model = "qwen3-vl:2b-instruct"
        self.num_thread = 0
        self.num_gpu = 99
        self.timeout = 60
        self.keep_alive = -1 # Keep loaded by default
        self.debug = False

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
                        target_lang: str = "English", mode: TranslationMode = TranslationMode.FULL_SCREEN,
                        original_size: QSize = QSize(0, 0), scaled_size: QSize = QSize(0, 0)) -> List[TranslationResult]:
        """Send image to Qwen3-VL for translation"""
        try:
            # Encode image to base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')

            if mode == TranslationMode.FULL_SCREEN:
                prompt = f"""<|im_start|>system
You are a professional translator and OCR engine.
Your task is to detect all text in the image and translate it to {target_lang}.
Return ONLY a JSON object with a "translations" list.

Rules:
1. "translated_text": MUST be in {target_lang}. NEVER return the original language (e.g. Chinese).
2. "x", "y", "width", "height": Use NORMALIZED coordinates [0 to 1000] relative to the image size.
   - (0,0) is top-left, (1000,1000) is bottom-right.
3. Group nearby words that form a single phrase or sentence into a single item.
4. Do not translate the same text multiple times.

Example:
{{
  "translations": [
    {{ "translated_text": "Hello World", "x": 100, "y": 150, "width": 200, "height": 50 }}
  ]
}}
<|im_end|>
<|im_start|>user
<|vision_start|><|image_pad|><|vision_end|>
Translate all text in this image to {target_lang}. Use normalized [0-1000] coordinates.
<|im_end|>
<|im_start|>assistant
"""
            else:
                prompt = f"""<|im_start|>system
You are a professional translator. Detect and translate the text in the image from {source_lang} to {target_lang}.
Return ONLY the translated text in {target_lang}. No preamble.
<|im_end|>
<|im_start|>user
<|vision_start|><|image_pad|><|vision_end|>Translate the text in this image to {target_lang}.
<|im_end|>
<|im_start|>assistant
"""

            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "format": "json" if mode == TranslationMode.FULL_SCREEN else "",
                "keep_alive": self.keep_alive,
                "options": {
                    "num_predict": 2048,
                    "temperature": 0,
                    "num_thread": self.num_thread if self.num_thread > 0 else None,
                    "num_gpu": self.num_gpu
                }
            }
            
            # Remove None values from options
            payload["options"] = {k: v for k, v in payload["options"].items() if v is not None}

            # Ensure base_url doesn't have a trailing slash to avoid double slashes
            url = self.base_url.rstrip('/') + "/api/generate"
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '')
                
                if self.debug:
                    print(f"Full API Prompt: {prompt}")
                    print(f"Full API Response: {content}")
                elif content:
                    # Log first bit of response for diagnostics
                    preview = content[:100].replace('\n', ' ')
                    print(f"API Response (first 100 chars): {preview}...")
                else:
                    print("API returned empty response content")
                
                # Apply scaling logic for both modes if they return multiple results (usually JSON)
                results = []
                if mode == TranslationMode.FULL_SCREEN:
                    results = self._parse_full_screen_response(content)
                else:
                    # Even in region mode, the model might return JSON if it's smart,
                    # but usually it returns raw text. Let's try to parse it just in case.
                    results = self._parse_full_screen_response(content)
                    if not results and content.strip():
                        results = [TranslationResult(content.strip(), 500, 500, 1000, 1000)] # Fill region

                # Scaling logic
                if results and original_size.width() > 0:
                    # We now strictly expect normalized [0, 1000]
                    # But we keep a heuristic for safety
                    max_coord = max(max(r.x + r.width, r.y + r.height) for r in results)
                    
                    is_normalized = True
                    if max_coord > 1100: # Clearly pixels
                        is_normalized = False
                    
                    if self.debug:
                        mode_str = "NORMALIZED" if is_normalized else "PIXELS"
                        print(f"Coordinate scaling: {mode_str} (max_coord={max_coord})")

                    scale_x = original_size.width() / 1000.0 if is_normalized else 1.0
                    scale_y = original_size.height() / 1000.0 if is_normalized else 1.0
                    
                    for r in results:
                        r.x = int(r.x * scale_x)
                        r.y = int(r.y * scale_y)
                        r.width = int(r.width * scale_x)
                        r.height = int(r.height * scale_y)
                
                return results
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
        """Parse JSON response from full screen mode with robust cleaning and truncation repair"""
        try:
            # Clean up content in case it's wrapped in markdown code blocks
            clean_content = content.strip()
            
            # Find the first '{' and last '}' to extract the JSON object
            # If no '}' is found, it might be truncated, so we take everything from the first '{'
            start_idx = clean_content.find('{')
            end_idx = clean_content.rfind('}')
            
            if start_idx != -1:
                if end_idx != -1 and end_idx > start_idx:
                    clean_content = clean_content[start_idx:end_idx + 1]
                else:
                    clean_content = clean_content[start_idx:]
            
            # --- Robust JSON Truncation Repair ---
            def repair_truncated_json(json_str):
                json_str = json_str.strip()
                if not json_str: return json_str
                stack = []
                in_string = False
                escaped = False
                for char in json_str:
                    if char == '"' and not escaped: in_string = not in_string
                    elif char == '\\' and in_string: escaped = not escaped
                    else: escaped = False
                    if not in_string:
                        if char == '{' or char == '[': stack.append(char)
                        elif char == '}' or char == ']':
                            if stack: stack.pop()
                if in_string: json_str += '"'
                if json_str.rstrip().endswith(':'): json_str += ' null'
                elif json_str.rstrip().endswith(','): json_str = json_str.rstrip()[:-1]
                while stack:
                    opening = stack.pop()
                    json_str += '}' if opening == '{' else ']'
                return json_str

            clean_content = repair_truncated_json(clean_content)

            # --- Robust JSON Cleaning ---
            # 1. Handle missing commas between objects in a list
            clean_content = re.sub(r'\}\s*\{', '},{', clean_content)
            
            # 2. Handle missing commas between key-value pairs or list items
            clean_content = re.sub(r'"\s*\n\s*"', '",\n"', clean_content)
            clean_content = re.sub(r'"\s*\n\s*\{', '",\n{', clean_content)
            clean_content = re.sub(r'\}\s*\n\s*"', '},\n"', clean_content)
            clean_content = re.sub(r'("\s*:\s*(?:true|false|null|\d+(?:\.\d+)?))\s*\n\s*"', r'\1,\n"', clean_content)
            clean_content = re.sub(r'("\s*:\s*"[^"]*")\s*\n\s*"', r'\1,\n"', clean_content)
            clean_content = re.sub(r'"\s+"', '", "', clean_content)

            # 3. Handle trailing commas in objects or lists
            clean_content = re.sub(r',\s*\}', '}', clean_content)
            clean_content = re.sub(r',\s*\]', ']', clean_content)

            # 4. Handle common unescaped quotes within translated text
            clean_content = re.sub(r'("\s*:\s*(?:true|false|null|\d+(?:\.\d+)?|"[^"]*"))\s+("[\w_]+")\s*:', r'\1,\n\2:', clean_content)
            
            try:
                data = json.loads(clean_content)
            except json.JSONDecodeError as e:
                # If still failing, try one more aggressive fix for common issues
                # 5. Fix missing commas between key-value pairs on the same line
                clean_content = re.sub(r'(\d|true|false|null|")\s+("[\w_]+")\s*:', r'\1,\n\2:', clean_content)
                
                # 6. Fix missing commas after strings on the same line
                clean_content = re.sub(r'("\s*:\s*"[^"]*")\s+("[\w_]+")\s*:', r'\1,\n\2:', clean_content)
                
                try:
                    data = json.loads(clean_content)
                except Exception as final_e:
                    print(f"Final JSON Parsing attempt failed: {final_e}")
                    raise final_e
            
            results = []

            for trans in data.get('translations', []):
                text = trans.get('translated_text', '')
                # Basic validation: ignore if text is empty or just whitespace
                if not text or not text.strip():
                    continue
                    
                results.append(TranslationResult(
                    translated_text=text,
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
            
            # Fallback: if we can't parse JSON, try to see if it's just raw text
            # but ONLY if it doesn't look like JSON (doesn't contain '{' or 'translations')
            # This prevents showing raw JSON in bubbles when parsing fails.
            if "{" not in content and "translations" not in content:
                return [TranslationResult(content.strip(), 100, 100, 200, 40)]
            
            return []

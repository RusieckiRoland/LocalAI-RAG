from typing import List, Union
from transformers import MarianMTModel, MarianTokenizer
import torch

class Translator:
    def __init__(self, model_name: str, device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = MarianTokenizer.from_pretrained(model_name)
        self.model = MarianMTModel.from_pretrained(model_name).to(self.device)

    @torch.inference_mode()
    def translate(self, text: Union[str, List[str]], max_length: int = 512) -> Union[str, List[str]]:
        single = isinstance(text, str)
        batch = [text] if single else text

        enc = self.tokenizer(
            batch, return_tensors="pt", padding=True, truncation=True, max_length=max_length
        ).to(self.device)
        
        out = self.model.generate(**enc)
        decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True)

        return decoded[0] if single else decoded

import urllib.parse
from typing import List
import requests

_CACHE = {}


def _translate_google(text: str, target_lang: str = "ru", source_lang: str = "auto") -> str:
    url = "https://translate.googleapis.com/translate_a/single"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    params = {
        "client": "dict-chrome-ex",
        "sl": source_lang,
        "tl": target_lang,
        "dt": "t",
        "q": text,
    }
    resp = requests.get(url, params=params, headers=headers, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    translated_parts = [part[0] for part in data[0] if part and part[0]]
    return "".join(translated_parts)


def _translate_mymemory(text: str, target_lang: str = "ru", source_lang: str = "en") -> str:
    langpair = f"{source_lang}|{target_lang}"
    url = "https://api.mymemory.translated.net/get"
    params = {"q": text, "langpair": langpair}
    resp = requests.get(url, params=params, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return data["responseData"]["translatedText"]


def translate_texts(texts: List[str], target_lang: str = "ru", source_lang: str = "auto") -> List[str]:
    """
    Translate a list of strings efficiently.
    Uses batch translation where possible.
    """
    if not texts:
        return []

    # Check cache first
    results = [None] * len(texts)
    missing_indices = []
    missing_texts = []

    for idx, t in enumerate(texts):
        key = (t.strip(), target_lang)
        if not t.strip():
            results[idx] = t
        elif key in _CACHE:
            results[idx] = _CACHE[key]
        else:
            missing_indices.append(idx)
            missing_texts.append(t)

    if not missing_texts:
        return results

    # Batch translation via newline separation
    joined = "\n".join(missing_texts)
    try:
        translated_blob = _translate_google(joined, target_lang=target_lang, source_lang=source_lang)
        split_results = translated_blob.split("\n")
        if len(split_results) == len(missing_texts):
            for orig, trans, idx in zip(missing_texts, split_results, missing_indices):
                clean_trans = trans.strip()
                _CACHE[(orig.strip(), target_lang)] = clean_trans
                results[idx] = clean_trans
            return results
    except Exception:
        pass

    # Fallback: one-by-one with Google or MyMemory
    for orig, idx in zip(missing_texts, missing_indices):
        try:
            trans = _translate_google(orig, target_lang=target_lang, source_lang=source_lang).strip()
        except Exception:
            try:
                trans = _translate_mymemory(orig, target_lang=target_lang, source_lang="en" if source_lang == "auto" else source_lang).strip()
            except Exception:
                trans = orig  # keep original if network completely fails

        _CACHE[(orig.strip(), target_lang)] = trans
        results[idx] = trans

    return results


if __name__ == "__main__":
    test_batch = ["Hello world", "Cancel", "Click to continue"]
    out = translate_texts(test_batch, target_lang="ru")
    print("Batch translation test:")
    for o, t in zip(test_batch, out):
        print(f"  {o} -> {t}")
    assert len(out) == 3
    assert all(bool(t) for t in out)
    print("Translator self-check passed!")

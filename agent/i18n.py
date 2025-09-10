import re
from langdetect import detect
from typing import Dict, Any

class LanguageDetector:
    def detect_language(self, text: str) -> str:
        """Detect language of input text with improved Sinhala detection"""
        try:
            # First check for Sinhala Unicode characters
            if self._contains_sinhala(text):
                return "si"
            
            # Check for Tamil Unicode characters
            if self._contains_tamil(text):
                return "ta"
            
            # Use langdetect for other languages
            detected = detect(text)
            # Map detected languages to our supported languages
            lang_map = {
                "si": "si",  # Sinhala
                "ta": "ta",  # Tamil
                "en": "en",  # English
            }
            return lang_map.get(detected, "en")
        except:
            # If langdetect fails, try Unicode range detection
            if self._contains_sinhala(text):
                return "si"
            elif self._contains_tamil(text):
                return "ta"
            return "en"  # Default to English
    
    def _contains_sinhala(self, text: str) -> bool:
        """Check if text contains Sinhala characters"""
        # Sinhala Unicode range: U+0D80–U+0DFF
        sinhala_pattern = r'[\u0D80-\u0DFF]'
        return bool(re.search(sinhala_pattern, text))
    
    def _contains_tamil(self, text: str) -> bool:
        """Check if text contains Tamil characters"""
        # Tamil Unicode range: U+0B80–U+0BFF
        tamil_pattern = r'[\u0B80-\u0BFF]'
        return bool(re.search(tamil_pattern, text))

# Multilingual text templates
TEXTS = {
    "menu": {
        "en": """🌟 Welcome to Safety Assistant! 🌟

Please select your preferred language:
1️⃣ සිංහල (Sinhala)
2️⃣ English
3️⃣ தமிழ் (Tamil)

Reply with 1, 2, or 3

💡 To change language anytime, type:
• "language" or "menu" (English)
• "භාෂාව" (Sinhala)  
• "மொழி" (Tamil)""",
        "si": """🌟 ආරක්ෂක සහායකයාට සාදරයෙන් පිළිගනිමු! 🌟

කරුණාකර ඔබේ භාෂාව තෝරන්න:
1️⃣ සිංහල
2️⃣ English
3️⃣ தமிழ்

1, 2, හෝ 3 සමඟ පිළිතුරු දෙන්න

💡 ඕනෑම වේලාවක භාෂාව වෙනස් කිරීමට ටයිප් කරන්න:
• "language" හෝ "menu" (English)
• "භාෂාව" (සිංහල)
• "மொழி" (Tamil)""",
        "ta": """🌟 பாதுகாப்பு உதவியாளருக்கு வரவேற்கிறோம்! 🌟

உங்கள் விருப்ப மொழியைத் தேர்ந்தெடுக்கவும்:
1️⃣ සිංහල
2️⃣ English  
3️⃣ தமிழ்

1, 2, அல்லது 3 உடன் பதிலளிக்கவும்

💡 எந்த நேரத்திலும் மொழியை மாற்ற டைப் செய்யுங்கள்:
• "language" அல்லது "menu" (English)
• "භාෂාව" (Sinhala)
• "மொழி" (தமிழ்)"""
    },
    
    "language_selected": {
        "en": """✅ Language set to English!

You can now ask me about:
• Safety procedures and guidelines
• Hazard identification and prevention  
• Emergency response protocols
• General safety questions

💡 Type "language" anytime to change language

How can I help you today?""",
        "si": """✅ භාෂාව සිංහලට සකසා ඇත!

ඔබට දැන් මගෙන් විමසිය හැක:
• ආරක්ෂක ක්‍රම සහ මාර්ගෝපදේශ
• අනතුරු හඳුනාගැනීම සහ වැළැක්වීම
• හදිසි ප්‍රතිචාර ප්‍රොටොකෝල්
• සාමාන්‍ය ආරක්ෂක ප්‍රශ්න

💡 භාෂාව වෙනස් කිරීමට ඕනෑම වේලාවක "භාෂාව" ටයිප් කරන්න

අද මට ඔබට කෙසේ උදව් කළ හැකිද?""",
        "ta": """✅ மொழி தமிழாக அமைக்கப்பட்டது!

நீங்கள் இப்போது என்னிடம் கேட்கலாம்:
• பாதுகாப்பு நடைமுறைகள் மற்றும் வழிகாட்டுதல்கள்
• ஆபத்து அடையாளம் மற்றும் தடுப்பு
• அவசரகால பதிலளிப்பு நெறிமுறைகள்
• பொதுவான பாதுகாப்பு கேள்விகள்

💡 மொழியை மாற்ற எந்த நேரத்திலும் "மொழி" என்று தட்டச்சு செய்யுங்கள்

இன்று நான் உங்களுக்கு எப்படி உதவ முடியும்?"""
    },
    
    "language_changed": {
        "en": "✅ Language changed to English",
        "si": "✅ භාෂාව සිංහලට වෙනස් කරන ලදී",
        "ta": "✅ மொழி தமிழுக்கு மாற்றப்பட்டது"
    },
    
    "web_search_limited": {
        "en": "I can help you with that, but web search is temporarily limited. Please try again in a few minutes, or ask me about safety topics from my knowledge base.",
        "si": "මට ඔබට ඒ ගැන උදව් කළ හැක, නමුත් වෙබ් සෙවීම තාවකාලිකව සීමිත ය. කරුණාකර මිනිත්තු කිහිපයකින් නැවත උත්සාහ කරන්න, නැතහොත් මගේ දැනුම් පදනමෙන් ආරක්ෂක මාතෘකා ගැන මගෙන් විමසන්න.",
        "ta": "அதில் நான் உங்களுக்கு உதவ முடியும், ஆனால் வலை தேடல் தற்காலிகமாக வரையறுக்கப்பட்டுள்ளது. தயவுசெய்து சில நிமிடங்களில் மீண்டும் முயற்சிக்கவும், அல்லது எனது அறிவுத் தளத்திலிருந்து பாதுகாப்பு தலைப்புகளைப் பற்றி என்னிடம் கேட்கவும்."
    },
    
    "no_answer": {
        "en": "I'm sorry, I don't have specific information about that. Could you try rephrasing your question or ask about general safety topics?",
        "si": "මට කණගාටුයි, ඒ ගැන නිශ්චිත තොරතුරු මා සතුව නැත. ඔබේ ප්‍රශ්නය නැවත වෙනස් කිරීමට හෝ සාමාන්‍ය ආරක්ෂක මාතෘකා ගැන විමසීමට හැකිද?",
        "ta": "மன்னிக்கவும், அது பற்றி எனக்கு குறிப்பிட்ட தகவல் இல்லை. உங்கள் கேள்வியை மறுபரிசீலனை செய்யலாமா அல்லது பொதுவான பாதுகாப்பு தலைப்புகளைப் பற்றி கேட்கலாமா?"
    },
    
    "error": {
        "en": "Sorry, I encountered an error. Please try again.",
        "si": "කණගාටුයි, මට දෝෂයක් ඇති විය. කරුණාකර නැවත උත්සාහ කරන්න.",
        "ta": "மன்னிக்கவும், எனக்கு பிழை ஏற்பட்டது. தயவுசெய்து மீண்டும் முயற்சிக்கவும்."
    }
}

def get_menu_text() -> str:
    """Get the language selection menu"""
    return TEXTS["menu"]["en"]

def get_response_text(key: str, language: str = "en") -> str:
    """Get localized response text"""
    return TEXTS.get(key, {}).get(language, TEXTS.get(key, {}).get("en", "Sorry, I couldn't process that."))

def translate_safety_terms(text: str, target_language: str) -> str:
    """Translate common safety terms"""
    safety_translations = {
        "si": {
            "safety": "ආරක්ෂාව",
            "hazard": "අනතුර",
            "emergency": "හදිසි",
            "warning": "අනතුරු ඇඟවීම",
            "danger": "භයානක",
            "accident": "අනතුර",
            "prevention": "වැළැක්වීම"
        },
        "ta": {
            "safety": "பாதுகாப்பு",
            "hazard": "ஆபத்து", 
            "emergency": "அவசரநிலை",
            "warning": "எச்சரிக்கை",
            "danger": "ஆபத்து",
            "accident": "விபத்து",
            "prevention": "தடுப்பு"
        }
    }
    
    if target_language not in safety_translations:
        return text
    
    translations = safety_translations[target_language]
    translated_text = text
    
    for english_term, translated_term in translations.items():
        translated_text = translated_text.replace(english_term, translated_term)
    
    return translated_text

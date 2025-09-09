from langdetect import detect
from typing import Dict, Any

class LanguageDetector:
    def detect_language(self, text: str) -> str:
        """Detect language of input text"""
        try:
            detected = detect(text)
            # Map detected languages to our supported languages
            lang_map = {
                "si": "si",  # Sinhala
                "ta": "ta",  # Tamil
                "en": "en",  # English
            }
            return lang_map.get(detected, "en")
        except:
            return "en"  # Default to English

# Multilingual text templates
TEXTS = {
    "menu": {
        "en": """🌟 Welcome to Safety Assistant! 🌟

Please select your preferred language:
1️⃣ සිංහල (Sinhala)
2️⃣ English
3️⃣ தமிழ் (Tamil)

Reply with 1, 2, or 3""",
        "si": """🌟 ආරක්ෂක සහායකයාට සාදරයෙන් පිළිගනිමු! 🌟

කරුණාකර ඔබේ භාෂාව තෝරන්න:
1️⃣ සිංහල
2️⃣ English
3️⃣ தமிழ்

1, 2, හෝ 3 සමඟ පිළිතුරු දෙන්න""",
        "ta": """🌟 பாதுகாப்பு உதவியாளருக்கு வரவேற்கிறோம்! 🌟

உங்கள் விருப்ப மொழியைத் தேர்ந்தெடுக்கவும்:
1️⃣ සිංහල
2️⃣ English  
3️⃣ தமிழ்

1, 2, அல்லது 3 உடன் பதிலளிக்கவும்"""
    },
    
    "language_selected": {
        "en": """✅ Language set to English!

You can now ask me about:
• Safety procedures and guidelines
• Hazard identification and prevention
• Emergency response protocols
• General safety questions

How can I help you today?""",
        "si": """✅ භාෂාව සිංහලට සකසා ඇත!

ඔබට දැන් මගෙන් විමසිය හැක:
• ආරක්ෂක ක්‍රම සහ මාර්ගෝපදේශ
• අනතුරු හඳුනාගැනීම සහ වැළැක්වීම
• හදිසි ප්‍රතිචාර ප්‍රොටොකෝල්
• සාමාන්‍ය ආරක්ෂක ප්‍රශ්න

අද මට ඔබට කෙසේ උදව් කළ හැකිද?""",
        "ta": """✅ மொழி தமிழாக அமைக்கப்பட்டது!

நீங்கள் இப்போது என்னிடம் கேட்கலாம்:
• பாதுகாப்பு நடைமுறைகள் மற்றும் வழிகாட்டுதல்கள்
• ஆபத்து அடையாளம் மற்றும் தடுப்பு
• அவசரகால பதிலளிப்பு நெறிமுறைகள்
• பொதுவான பாதுகாப்பு கேள்விகள்

இன்று நான் உங்களுக்கு எப்படி உதவ முடியும்?"""
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

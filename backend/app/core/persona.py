"""Kamlesh Bhai — the TaskPilot AI assistant persona.

Friendly, intelligent, witty and reliable. Kamlesh Bhai mirrors the user's
language: English in -> English out, Hindi (Devanagari) in -> Hindi out,
Hinglish (romanised Hindi mixed with English) in -> Hinglish out.

`detect_language()` is a cheap deterministic hint; in Phase 2 the LLM classifier
also reports the language and the planner writes the user-facing reply. The
templates below cover messages trusted code must produce itself (acknowledgements,
failures, fallbacks when a model reply is unusable).
"""

from __future__ import annotations

import re
from typing import Literal

Language = Literal["en", "hi", "hinglish"]

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[a-z]+")

# Common romanised-Hindi tokens. Chosen to avoid collisions with frequent English words.
_HINGLISH_MARKERS = frozenset(
    {
        "kya", "hai", "hain", "kar", "karo", "karna", "karde", "kardo", "mujhe", "mera", "meri",
        "mere", "aur", "bhai", "yaar", "chahiye", "dikhao", "kholo", "khol", "dhundo", "dhoondo",
        "batao", "bata", "acha", "accha", "theek", "thik", "nahi", "nahin", "haan", "abhi",
        "jaldi", "wala", "wali", "liye", "kaise", "kitna", "kitne", "sasta", "dekho", "ek", "do",
        "teen", "daal", "dalo", "mein", "ko", "ka", "ki", "ke", "se", "bhi", "toh", "tum", "aap",
        "hum", "pe", "par", "lao", "laao", "chalo", "bolo", "samjha", "matlab",
    }
)
# These overlap with English ("do", "to", "par") so they only count alongside other markers.
_WEAK_MARKERS = frozenset({"do", "par", "pe", "ko", "ka", "ki", "ke", "se", "ek"})


def detect_language(text: str) -> Language:
    """Best-effort language detection used to mirror the user's language."""
    devanagari = len(_DEVANAGARI.findall(text))
    latin = len(_LATIN.findall(text))
    if devanagari and devanagari >= latin:
        return "hi"
    words = _WORD.findall(text.lower())
    if not words:
        return "en"
    strong = sum(1 for w in words if w in _HINGLISH_MARKERS and w not in _WEAK_MARKERS)
    weak = sum(1 for w in words if w in _WEAK_MARKERS)
    if devanagari or strong >= 2 or (strong >= 1 and weak >= 1):
        return "hinglish"
    return "en"


_ACK: dict[Language, str] = {
    "en": (
        "Got it! I've noted your task. My planning brain arrives in the next phase, "
        "so I'm not touching any website yet."
    ),
    "hinglish": (
        "Samajh gaya bhai! Task note kar liya hai. Planning wala dimaag agle phase mein aayega, "
        "abhi main kisi website ko haath nahi laga raha."
    ),
    "hi": (
        "समझ गया! आपका टास्क नोट कर लिया है। प्लानिंग अगले फ़ेज़ में आएगी, "
        "अभी मैं किसी वेबसाइट पर कुछ नहीं कर रहा हूँ।"
    ),
}


def task_acknowledgement(command: str) -> tuple[str, Language]:
    """Phase 1 acknowledgement (used when AGENT_PLANNING_ENABLED=false)."""
    language = detect_language(command)
    return _ACK[language], language


ASSISTANT_NAME = "Kamlesh Bhai"

KAMLESH_SYSTEM_PERSONA = """
You are Kamlesh Bhai, the intelligent AI assistant inside TaskPilot AI.

Personality: friendly, intelligent, practical, reliable and conversational; slightly witty
when appropriate, professional during important operations.

Language: if the user writes Hinglish, reply naturally in Hinglish; if Hindi, reply in Hindi;
if English, reply in English. Do not switch languages unnecessarily.

You help users accomplish tasks through browser automation, but only actions explicitly
supported by the system can be planned. Never claim that a website action was completed when
it has only been planned. Explain what you understood, what you intend to do and what
information you still need. Never expose internal chain-of-thought; give concise summaries,
actionable plans and important assumptions instead.
""".strip()

_TEMPLATES: dict[str, dict[Language, str]] = {
    "acknowledgement": {
        "en": "Got it! Let me put together a plan for that.",
        "hinglish": "Haan bhai! Samajh gaya, plan bana raha hoon.",
        "hi": "समझ गया! आपके लिए प्लान बना रहा हूँ।",
    },
    "planning_started": {
        "en": "Kamlesh Bhai is preparing your action plan.",
        "hinglish": "Kamlesh Bhai tumhara action plan bana raha hai.",
        "hi": "कमलेश भाई आपका एक्शन प्लान बना रहे हैं।",
    },
    "clarification_received": {
        "en": "Thanks! Updating the plan with that.",
        "hinglish": "Thanks bhai! Ab plan update kar raha hoon.",
        "hi": "धन्यवाद! अब प्लान अपडेट कर रहा हूँ।",
    },
    "plan_ready": {
        "en": "Your plan is ready. Nothing has run yet — review it and click Run Plan to execute it in the browser.",
        "hinglish": "Plan ready hai bhai! Abhi kuch run nahi hua — dekh lo, phir Run Plan dabao toh browser mein chalaunga.",
        "hi": "प्लान तैयार है। अभी कुछ नहीं चला — देख लीजिए, फिर Run Plan दबाने पर ब्राउज़र में चलाऊँगा।",
    },
    "clarification": {
        "en": "Could you share a bit more detail?",
        "hinglish": "Bhai, thoda aur detail doge?",
        "hi": "क्या आप थोड़ा और विवरण देंगे?",
    },
    "rejected": {
        "en": "Sorry, I can't plan that. I only plan safe, supported browser tasks.",
        "hinglish": "Sorry bhai, ye main plan nahi kar sakta. Sirf safe aur supported browser tasks.",
        "hi": "माफ़ कीजिए, यह मैं प्लान नहीं कर सकता। केवल सुरक्षित, समर्थित ब्राउज़र कार्य।",
    },
    "execution_completed": {
        "en": "Done! I ran every step in the browser and checked the results. Nothing was bought or paid for.",
        "hinglish": "Ho gaya bhai! Browser mein saare steps chala ke results check kar liye. Kuch khareeda ya pay nahi kiya.",
        "hi": "हो गया! ब्राउज़र में सारे स्टेप चलाकर नतीजे जाँच लिए। कुछ खरीदा या भुगतान नहीं किया गया।",
    },
    "order_placed": {
        "en": "Done! After your final approval I placed the cash-on-delivery order once, and the website shows it as confirmed.",
        "hinglish": "Ho gaya bhai! Tumhari final approval ke baad COD order ek baar place kiya, website pe confirm dikh raha hai.",
        "hi": "हो गया! आपकी अंतिम मंज़ूरी के बाद कैश-ऑन-डिलीवरी ऑर्डर एक बार दिया, वेबसाइट पर पुष्टि दिख रही है।",
    },
    "payment_handoff": {
        "en": "Your cart and checkout are ready. Please complete the payment yourself on the website — I never pay for you.",
        "hinglish": "Cart aur checkout ready hai bhai. Payment tum khud website pe kar lo — main kabhi pay nahi karta.",
        "hi": "कार्ट और चेकआउट तैयार हैं। कृपया भुगतान वेबसाइट पर स्वयं करें — मैं कभी भुगतान नहीं करता।",
    },
    # Phase 5 integrations
    "integration_completed": {
        "en": "Done! Every step ran in the browser and I checked each result on the page.",
        "hinglish": "Ho gaya bhai! Saare steps browser mein chale aur har result page pe check kar liya.",
        "hi": "हो गया! हर स्टेप ब्राउज़र में चला और मैंने हर नतीजा पेज पर जाँच लिया।",
    },
    "draft_saved": {
        "en": "Done! The email draft is saved in Gmail Drafts. It has NOT been sent — you can review and send it yourself.",
        "hinglish": "Haan bhai, main email ka draft prepare kar sakta hoon. Final Send tum Gmail se manually kar sakte ho. Draft Gmail Drafts mein save ho gaya hai.",
        "hi": "हो गया! ईमेल का ड्राफ़्ट Gmail Drafts में सेव है। इसे भेजा नहीं गया — आप जाँचकर ख़ुद भेज सकते हैं।",
    },
    "event_created": {
        "en": "Done! After your approval I created exactly that event and found it on your calendar.",
        "hinglish": "Ho gaya bhai! Tumhari approval ke baad wahi exact event bana diya aur calendar pe dikh raha hai.",
        "hi": "हो गया! आपकी मंज़ूरी के बाद वही इवेंट बनाया और वह आपके कैलेंडर पर दिख रहा है।",
    },
    "workflow_partial": {
        "en": "Part of the workflow finished. The workflow panel shows exactly which steps worked and which did not.",
        "hinglish": "Bhai, workflow ka kuch hissa hi poora hua. Workflow panel mein dekh lo kaunse steps chale aur kaunse nahi.",
        "hi": "वर्कफ़्लो का कुछ हिस्सा ही पूरा हुआ। वर्कफ़्लो पैनल में देखें कौन-से स्टेप चले और कौन-से नहीं।",
    },
    "execution_cancelled": {
        "en": "I stopped the run. The browser is still open so you can check where it ended.",
        "hinglish": "Run rok diya bhai. Browser khula hai, dekh lo kahan tak pahuncha.",
        "hi": "रन रोक दिया। ब्राउज़र खुला है, आप देख सकते हैं कहाँ तक पहुँचा।",
    },
    "execution_failed": {
        "en": "A step didn't work in the browser, so I stopped there. The timeline shows exactly what happened.",
        "hinglish": "Bhai, browser mein ek step nahi chala, isliye wahi ruk gaya. Timeline mein sab dikh raha hai.",
        "hi": "ब्राउज़र में एक स्टेप नहीं चला, इसलिए वहीं रुक गया। टाइमलाइन में पूरी जानकारी है।",
    },
    "failed": {
        "en": "Sorry, I couldn't finish planning this time. Please try again.",
        "hinglish": "Sorry bhai, is baar plan nahi ban paaya. Ek baar phir try karo.",
        "hi": "माफ़ कीजिए, इस बार प्लान नहीं बन पाया। कृपया फिर से कोशिश करें।",
    },
}


def persona_message(kind: str, language: Language = "en") -> str:
    templates = _TEMPLATES[kind]
    return templates.get(language, templates["en"])

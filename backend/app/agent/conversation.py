"""Kamlesh Bhai's casual conversation (no browser involved).

Used by the offline planner for GENERAL_CHAT replies, and as a language/name-aware fallback. With a real LLM
provider configured, chat replies come from the model (see prompts.py) and this module is not used for them.

Replies are short, warm and match the user's language (English / Hindi / Hinglish). The user's preferred name
comes from Settings; nothing is guessed — without a name we simply say "bhai".
"""

from __future__ import annotations

import re
from typing import Literal

Language = Literal["en", "hi", "hinglish"]

_HOW_ARE_YOU = re.compile(
    r"\b(how are you|how're you|how r u|how do you do|kaise ho|kaisa hai|kaise hain|kya haal|kya hal|kya haal hai|"
    r"sab badhiya|sab theek|what'?s up|wassup|sup)\b|कैसे हो|कैसे हैं|क्या हाल",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^\W*(hi+|hello+|hey+|hola|namaste|namaskar|pranam|ram ram|salaam|good (morning|afternoon|evening|night))\b|"
    r"^\W*(नमस्ते|नमस्कार|प्रणाम)",
    re.IGNORECASE,
)
_THANKS = re.compile(r"\b(thanks|thank you|thx|shukriya|dhanyavaad|dhanyawad|thank u)\b|धन्यवाद|शुक्रिया", re.IGNORECASE)
_BYE = re.compile(r"\b(bye|good ?bye|see you|chalo bye|alvida|phir milte)\b|अलविदा", re.IGNORECASE)
_WHO = re.compile(r"\b(who are you|tum kaun ho|aap kaun ho|your name|tumhara naam|aapka naam)\b|तुम कौन|आप कौन", re.IGNORECASE)
_HELP = re.compile(
    r"\b(what can you do|what do you do|help me|help|kya kar sakte|kya kya kar sakte|kya karte ho|supported|capabilit\w*|"
    r"features?|kaise use|how (do|to) (i )?use)\b|क्या कर सकते",
    re.IGNORECASE,
)
_JOKE = re.compile(r"\b(joke|majak|mazaak|chutkula)\b|चुटकुला", re.IGNORECASE)
_GOOD = re.compile(r"\b(i'?m (good|fine|great|ok)|main (theek|badhiya|mast)|sab (badhiya|theek|mast)|all good|badhiya hoon|theek hoon)\b",
                   re.IGNORECASE)
_OPEN_UNKNOWN = re.compile(r"\b(open|kholo|khol do|launch)\b", re.IGNORECASE)


def _who(name: str | None, lang: Language) -> str:
    if name:
        return f"{name} bhai" if lang != "hi" else f"{name} जी"
    return "bhai" if lang != "hi" else ""


def small_talk_reply(text: str, lang: Language, name: str | None = None) -> str:
    """A natural, short reply for conversation that needs no browser."""
    low = text.lower().strip()
    who = _who(name, lang)
    friend = f" {who}" if who else ""

    if _HOW_ARE_YOU.search(low):
        return _say(lang,
                    f"Hey{friend}! I'm doing great, thanks for asking. How about you — what's on your mind today?",
                    f"Arey{friend}! Main badhiya hoon. Tum batao, kaise ho? Aaj kya karna hai?",
                    f"अरे{friend}! मैं बढ़िया हूँ। आप बताइए, कैसे हैं? आज क्या करना है?")
    if _GOOD.search(low):
        return _say(lang, f"Love to hear that{friend}! Tell me whenever you need something done on the web.",
                    f"Badhiya{friend}! Jab bhi web pe kuch karwana ho, bas bol dena.",
                    "बढ़िया! जब भी वेब पर कुछ करवाना हो, बस बता दीजिए।")
    if _THANKS.search(low):
        return _say(lang, f"Anytime{friend}! Happy to help.", f"Arey koi baat nahi{friend}! Kabhi bhi bolo.",
                    "कोई बात नहीं! कभी भी बताइए।")
    if _BYE.search(low):
        return _say(lang, f"Bye{friend}! Take care.", f"Chalo{friend}, milte hain! Apna dhyan rakhna.", "फिर मिलते हैं! अपना ध्यान रखिए।")
    if _WHO.search(low):
        return _say(lang,
                    "I'm Kamlesh Bhai, your browser assistant. I can chat, and I can open sites like Blinkit or Amazon, "
                    "search, fill your cart, find YouTube videos, draft emails and set up calendar events — always asking "
                    "before anything sensitive.",
                    "Main Kamlesh Bhai hoon, tumhara browser assistant. Baat bhi kar sakta hoon, aur Blinkit/Amazon kholna, "
                    "search karna, cart mein saaman daalna, YouTube video dhundhna, email draft aur calendar event — sab kar "
                    "deta hoon. Payment ya order jaise kaam se pehle hamesha poochta hoon.",
                    "मैं कमलेश भाई हूँ, आपका ब्राउज़र असिस्टेंट। बातचीत के साथ Blinkit/Amazon खोलना, सर्च, कार्ट में सामान "
                    "डालना, YouTube, ईमेल ड्राफ़्ट और कैलेंडर — सब कर सकता हूँ। संवेदनशील काम से पहले हमेशा पूछता हूँ।")
    if _HELP.search(low):
        return _say(lang,
                    "Here's what I can do: open websites (\"open Blinkit\"), add groceries to your cart (\"add 2 litre Amul milk "
                    "on Blinkit\"), search products on Amazon, play YouTube videos, save Gmail drafts and create calendar events. "
                    "Payments, placing orders and sending emails always need your explicit approval — or you do them yourself.",
                    "Ye sab kar sakta hoon: website kholna (\"Blinkit kholo\"), cart mein saaman daalna (\"Blinkit pe 2 litre Amul "
                    "milk add karo\"), Amazon pe search, YouTube video chalana, Gmail draft aur calendar event. Payment, order "
                    "place karna ya email bhejna — ye hamesha tumhari approval se, ya tum khud karte ho.",
                    "मैं ये कर सकता हूँ: वेबसाइट खोलना (\"Blinkit खोलो\"), कार्ट में सामान डालना, Amazon पर सर्च, YouTube, "
                    "Gmail ड्राफ़्ट और कैलेंडर इवेंट। पेमेंट, ऑर्डर या ईमेल भेजना हमेशा आपकी मंज़ूरी से।")
    if _JOKE.search(low):
        return _say(lang, "Why did the shopping cart go to therapy? It had too many unresolved items! 😄",
                    "Ek baar cart ne therapist se kaha — mere andar itna saaman hai, par koi checkout hi nahi karta! 😄",
                    "एक बार कार्ट ने कहा — मेरे अंदर इतना सामान है, पर कोई चेकआउट ही नहीं करता! 😄")
    if _GREETING.search(low):
        return _say(lang,
                    f"Hey{friend}! Good to hear from you. How are you doing? Tell me if there's anything I can do for you.",
                    f"Arey{friend}, namaste! Kaise ho? Batao, aaj kya karwana hai?",
                    f"नमस्ते{friend}! कैसे हैं? बताइए, आज क्या करना है?")
    if _OPEN_UNKNOWN.search(low):
        return _say(lang,
                    "Sure — which website should I open? I work with Blinkit, Amazon, YouTube, Google, Gmail, Google Calendar "
                    "and a few more. (I can't open desktop apps like Opera — only websites inside my browser.)",
                    "Haan bhai, kaunsi website kholun? Blinkit, Amazon, YouTube, Google, Gmail, Calendar jaisi sites khol sakta "
                    "hoon. (Opera jaise desktop apps nahi — sirf mere browser ke andar websites.)",
                    "कौनसी वेबसाइट खोलूँ? Blinkit, Amazon, YouTube, Google, Gmail जैसी साइटें खोल सकता हूँ।")
    return _say(lang,
                f"I'm not sure I followed that{friend}. We can just chat, or tell me something to do on the web — for example "
                "\"open Blinkit\" or \"add 2 litre Amul milk to my Blinkit cart\".",
                f"Bhai{friend if who != 'bhai' else ''}, ye thoda samajh nahi aaya. Normal baat karo, ya web pe kuch karwana ho toh bolo — jaise \"Blinkit kholo\" "
                "ya \"Blinkit pe 2 litre Amul milk add karo\".",
                "यह ठीक से समझ नहीं आया। बात कीजिए, या वेब पर कुछ करवाना हो तो बताइए — जैसे \"Blinkit खोलो\"।")


def _say(lang: Language, en: str, hinglish: str, hi: str) -> str:
    return {"en": en, "hinglish": hinglish, "hi": hi}.get(lang, en)


def is_small_talk(text: str) -> bool:
    low = text.lower()
    return any(p.search(low) for p in (_HOW_ARE_YOU, _GREETING, _THANKS, _BYE, _WHO, _HELP, _JOKE, _GOOD))

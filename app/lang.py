# app/lang.py
# Language helper functions

from flask import session, request, g
from app.translations import TRANSLATIONS, get_translation, get_all_translations

DEFAULT_LANGUAGE = 'ku'  # Kurdish as default
SUPPORTED_LANGUAGES = ['ku', 'ar', 'en']

LANGUAGE_NAMES = {
    'ku': 'کوردی',
    'ar': 'العربية', 
    'en': 'English'
}

LANGUAGE_FLAGS = {
    'ku': '🇮🇶',
    'ar': '🇸🇦',
    'en': '🇬🇧'
}


def get_locale():
    """Get current language from session or default"""
    return session.get('lang', DEFAULT_LANGUAGE)


def set_locale(lang):
    """Set language in session"""
    if lang in SUPPORTED_LANGUAGES:
        session['lang'] = lang
        return True
    return False


def t(key):
    """Shortcut function for translation"""
    lang = get_locale()
    return get_translation(key, lang)


def init_language(app):
    """Initialize language system with Flask app"""
    
    @app.before_request
    def before_request():
        # Set language from URL parameter if provided
        lang = request.args.get('lang')
        if lang and lang in SUPPORTED_LANGUAGES:
            session['lang'] = lang
        
        # Make current language available in g
        g.lang = get_locale()
        g.translations = get_all_translations(g.lang)
    
    @app.context_processor
    def inject_language():
        """Inject language variables into all templates"""
        lang = get_locale()
        return {
            'current_lang': lang,
            'languages': SUPPORTED_LANGUAGES,
            'language_names': LANGUAGE_NAMES,
            'language_flags': LANGUAGE_FLAGS,
            't': lambda key: get_translation(key, lang),
            'trans': get_all_translations(lang),
            'is_rtl': lang in ['ku', 'ar']  # RTL for Kurdish and Arabic
        }

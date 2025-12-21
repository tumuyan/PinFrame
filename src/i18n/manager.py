import json
import os

class I18nManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self.current_lang = "en_US"
        self.translations = {}
        self._initialized = True
        
    def load_language(self, lang_code):
        self.current_lang = lang_code
        # Local path to i18n folder
        base_path = os.path.dirname(__file__)
        file_path = os.path.join(base_path, f"{lang_code}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations = json.load(f)
            except Exception as e:
                print(f"Error loading i18n file: {e}")
                self.translations = {}
        else:
            print(f"Warning: Translation file for {lang_code} not found at {file_path}")
            self.translations = {}
            
    def t(self, key, default=None):
        if default is None:
            default = key
        return self.translations.get(key, default)

    def get_current_language(self):
        return self.current_lang

# Singleton instance
i18n = I18nManager()

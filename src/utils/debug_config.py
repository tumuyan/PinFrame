"""
Debug logging configuration module.
Controls which debug messages are printed to console.
"""
from typing import Set, List
import json
import os
from i18n.manager import i18n


class DebugConfig:
    """Singleton class to manage debug logging settings"""
    
    _instance = None
    
    # Category keys (display names are i18n keys) - reversed order
    CATEGORY_KEYS = ["import", "export", "property", "canvas", "timeline", "grid_text"]
    
    # I18n keys for category display names
    CATEGORY_I18N_KEYS = {
        "grid_text": "debug_cat_timeline_graidview",
        "timeline": "debug_cat_timeline",
        "canvas": "debug_cat_canvas",
        "property": "debug_cat_property",
        "export": "debug_cat_export",
        "import": "debug_cat_import",
    }
    
    # Default enabled categories (grid_text disabled by default, others enabled)
    DEFAULT_ENABLED = {"timeline", "canvas", "property", "export", "import"}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._enabled_categories: Set[str] = set()
            cls._instance._master_enabled: bool = True
            cls._instance._load_settings()
        return cls._instance
    
    def _load_settings(self):
        """Load settings from config file"""
        config_path = self._get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._enabled_categories = set(data.get("enabled_categories", []))
                    self._master_enabled = data.get("master_enabled", True)
            except (json.JSONDecodeError, IOError):
                # On error, use defaults
                self._enabled_categories = self.DEFAULT_ENABLED.copy()
                self._master_enabled = True
        else:
            # Default: grid_text disabled, others enabled
            self._enabled_categories = self.DEFAULT_ENABLED.copy()
            self._master_enabled = True
    
    def _save_settings(self):
        """Save settings to config file"""
        config_path = self._get_config_path()
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "enabled_categories": list(self._enabled_categories),
                    "master_enabled": self._master_enabled
                }, f, indent=2)
        except IOError:
            pass
    
    def _get_config_path(self) -> str:
        """Get the path to the config file"""
        # Store in user's config directory
        config_dir = os.path.join(os.path.expanduser("~"), ".pinframe")
        return os.path.join(config_dir, "debug_config.json")
    
    def is_enabled(self, category: str) -> bool:
        """Check if a debug category is enabled (also checks master switch)"""
        return self._master_enabled and category in self._enabled_categories
    
    def is_master_enabled(self) -> bool:
        """Check if master debug switch is enabled"""
        return self._master_enabled
    
    def set_master_enabled(self, enabled: bool):
        """Enable or disable master debug switch"""
        self._master_enabled = enabled
        self._save_settings()
    
    def set_enabled(self, category: str, enabled: bool):
        """Enable or disable a debug category"""
        if enabled:
            self._enabled_categories.add(category)
        else:
            self._enabled_categories.discard(category)
        self._save_settings()
    
    def get_all_categories(self) -> dict:
        """Get all available categories with their display names"""
        return {key: i18n.t(self.CATEGORY_I18N_KEYS.get(key, key), key) 
                for key in self.CATEGORY_KEYS}
    
    def get_enabled_categories(self) -> Set[str]:
        """Get set of enabled categories"""
        return self._enabled_categories.copy()
    
    def set_enabled_categories(self, categories: Set[str]):
        """Set all enabled categories at once"""
        self._enabled_categories = categories.copy()
        self._save_settings()


# Global function for easy access
def debug_print(category: str, *args, **kwargs):
    """Print debug message if category is enabled"""
    config = DebugConfig()
    if config.is_enabled(category):
        print(*args, **kwargs)


def debug_print_lines(category: str, lines: List[str], **kwargs):
    """
    Print multiple lines of debug message if category is enabled.
    More efficient than multiple debug_print calls.
    
    Args:
        category: Debug category to check
        lines: List of lines to print
        **kwargs: Additional print arguments
    """
    config = DebugConfig()
    if config.is_enabled(category):
        for line in lines:
            print(line, **kwargs)


# Convenience functions for each debug category
def grid_text_debug(*args, **kwargs):
    """Print grid text debug message if enabled"""
    debug_print("grid_text", *args, **kwargs)


def grid_text_debug_lines(lines: List[str], **kwargs):
    """
    Print multiple lines of grid text debug message if enabled.
    More efficient than multiple grid_text_debug calls.
    
    Args:
        lines: List of lines to print
        **kwargs: Additional print arguments
    """
    debug_print_lines("grid_text", lines, **kwargs)


def timeline_debug(*args, **kwargs):
    """Print timeline debug message if enabled"""
    debug_print("timeline", *args, **kwargs)


def canvas_debug(*args, **kwargs):
    """Print canvas debug message if enabled"""
    debug_print("canvas", *args, **kwargs)


def property_debug(*args, **kwargs):
    """Print property debug message if enabled"""
    debug_print("property", *args, **kwargs)


def export_debug(*args, **kwargs):
    """Print export debug message if enabled"""
    debug_print("export", *args, **kwargs)


def import_debug(*args, **kwargs):
    """Print import debug message if enabled"""
    debug_print("import", *args, **kwargs)

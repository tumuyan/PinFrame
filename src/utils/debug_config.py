"""
Debug logging configuration module.
Controls which debug messages are printed to console.
"""
from typing import Set, List, Any
import json
import os


class DebugConfig:
    """Singleton class to manage debug logging settings"""
    
    _instance = None
    
    # Available debug categories
    CATEGORIES = {
        "grid_text": "GridText 日志 (网格视图文字)",
        "timeline": "Timeline 时间轴",
        "canvas": "Canvas 画布",
        "property": "Property 属性面板",
        "export": "Export 导出",
        "import": "Import 导入",
    }
    
    # Default enabled categories (grid_text disabled by default, others enabled)
    DEFAULT_ENABLED = {"timeline", "canvas", "property", "export", "import"}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._enabled_categories: Set[str] = set()
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
            except (json.JSONDecodeError, IOError):
                # On error, use defaults
                self._enabled_categories = self.DEFAULT_ENABLED.copy()
        else:
            # Default: grid_text disabled, others enabled
            self._enabled_categories = self.DEFAULT_ENABLED.copy()
    
    def _save_settings(self):
        """Save settings to config file"""
        config_path = self._get_config_path()
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "enabled_categories": list(self._enabled_categories)
                }, f, indent=2)
        except IOError:
            pass
    
    def _get_config_path(self) -> str:
        """Get the path to the config file"""
        # Store in user's config directory
        config_dir = os.path.join(os.path.expanduser("~"), ".pinframe")
        return os.path.join(config_dir, "debug_config.json")
    
    def is_enabled(self, category: str) -> bool:
        """Check if a debug category is enabled"""
        return category in self._enabled_categories
    
    def set_enabled(self, category: str, enabled: bool):
        """Enable or disable a debug category"""
        if enabled:
            self._enabled_categories.add(category)
        else:
            self._enabled_categories.discard(category)
        self._save_settings()
    
    def get_all_categories(self) -> dict:
        """Get all available categories with their display names"""
        return self.CATEGORIES.copy()
    
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

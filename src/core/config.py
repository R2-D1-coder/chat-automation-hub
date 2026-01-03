"""配置加载模块"""
import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent.parent / "config.json"


def load_config(config_path: Path = CONFIG_FILE) -> dict:
    """加载 JSON 配置文件"""
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


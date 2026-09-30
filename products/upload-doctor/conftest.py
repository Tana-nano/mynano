import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE / "tests"))

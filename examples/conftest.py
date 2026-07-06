import sys
from pathlib import Path

# examples are tested from the backend venv; make lga + _shared importable
sys.path.insert(0, str(Path(__file__).parent))

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["USE_MOCK_DB"] = "true"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"
import tempfile
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="mm_storage_")
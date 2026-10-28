import os
import re
import runpy
import shutil
import tempfile
from pathlib import Path

import pytest

NONET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nonet")
os.environ["PYTHONPATH"] = os.pathsep.join(
    filter(None, [NONET_DIR, os.environ.get("PYTHONPATH")])
)
runpy.run_path(os.path.join(NONET_DIR, "sitecustomize.py"))

TESTS_DIR = Path(__file__).parent
DB_STUB_DIR = Path(tempfile.mkdtemp(prefix="chgksuite_db_stub_"))
os.environ["CHGKSUITE_DB_URL"] = DB_STUB_DIR.as_uri() + "/"


def stub_db_handouts():
    """Serve tests/test.jpg under every (pic: ...) name the test packets use."""
    images = DB_STUB_DIR / "images" / "db"
    images.mkdir(parents=True)
    for txt in TESTS_DIR.glob("*.txt"):
        for name in re.findall(rb"\(pic:\s([\w.]+)\)", txt.read_bytes(), re.I):
            shutil.copy(TESTS_DIR / "test.jpg", images / name.decode())


stub_db_handouts()


def pytest_sessionfinish(session):
    shutil.rmtree(DB_STUB_DIR, ignore_errors=True)


def pytest_addoption(parser):
    parser.addoption("--pdf", action="store_true", help="run pdf tests")
    parser.addoption(
        "--parsing_engine",
        action="store",
        default="python_docx",
        help="identical to gui option",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "pdf: tests that require typst")


def pytest_runtest_setup(item):
    if "pdf" in item.keywords and not item.config.getoption("--pdf", default=False):
        pytest.skip("need --pdf option to run this test")


@pytest.fixture
def parsing_engine(request):
    return request.config.getoption("--parsing_engine", default="python_docx")

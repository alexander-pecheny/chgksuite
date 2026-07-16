import pytest


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

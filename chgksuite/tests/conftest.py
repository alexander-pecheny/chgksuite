import pytest


def pytest_addoption(parser):
    parser.addoption("--tex", action="store_true", help="run tex tests")
    parser.addoption(
        "--parsing_engine",
        action="store",
        default="mammoth",
        help="identical to gui option",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "tex: tests that require TeX")


def pytest_runtest_setup(item):
    if "tex" in item.keywords and not item.config.getoption("--tex", default=False):
        pytest.skip("need --tex option to run this test")


@pytest.fixture
def parsing_engine(request):
    return request.config.getoption("--parsing_engine", default="mammoth")

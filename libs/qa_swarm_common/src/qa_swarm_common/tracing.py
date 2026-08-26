from contextlib import contextmanager

from lmnr import Laminar


def init_tracing(project_api_key: str | None) -> None:
    if not project_api_key:
        return
    Laminar.initialize(project_api_key=project_api_key, instruments=set())


@contextmanager
def traced_span(name: str, session_id: str | None = None):
    if not Laminar.is_initialized():
        yield
        return
    with Laminar.start_as_current_span(name=name, session_id=session_id):
        yield

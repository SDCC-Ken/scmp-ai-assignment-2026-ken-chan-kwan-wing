"""Offline smoke tests proving every runtime dependency installs and works."""

from typing import TypedDict

import httpx
import pydantic
import sqlalchemy
from langgraph.graph import END, START, StateGraph


def test_fastapi_and_pydantic_import() -> None:
    import fastapi

    class Model(pydantic.BaseModel):
        x: int

    assert Model(x="1").x == 1
    assert fastapi.FastAPI is not None


def test_sqlalchemy_in_memory_sqlite() -> None:
    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        assert conn.execute(sqlalchemy.text("SELECT 1")).scalar() == 1


def test_httpx_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = client.post("http://mock.invalid/api/users", json={"a": 1})
    assert response.status_code == 201
    assert response.json() == {"id": "1"}


def test_langgraph_single_node() -> None:
    class State(TypedDict):
        value: int

    def bump(state: State) -> State:
        return {"value": state["value"] + 1}

    graph = StateGraph(State)
    graph.add_node("bump", bump)
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)
    assert graph.compile().invoke({"value": 1}) == {"value": 2}


def test_google_genai_import_only() -> None:
    from google import genai
    from google.genai import types

    assert genai.Client is not None
    assert types.GenerateContentConfig is not None

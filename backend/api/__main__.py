from datetime import datetime
import json
import asyncpg
from loguru import logger
import os
from graphrag_processing import get_search_engine

from pydantic import BaseModel
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal

import re
from uvicorn import run


from pg import (
    check_historical_prompt_response,
    connect,
    disconnect,
    get_connection_pool,
    get_prompts_history,
    save_prompt_response,
)


app = FastAPI()

app.add_event_handler("startup", connect)
app.add_event_handler("shutdown", disconnect)


AVAILABLE_GRAPHS = [
    {"path": "data/graphs/podcast", "id": "podcast", "name": "podcast"},
    {"path": "data/graphs/gazeta", "id": "gazeta", "name": "gazeta"},
]


class PromptResponse(BaseModel):
    response: str


class PromptHistory(BaseModel):
    prompt: str
    nodes: list[str]


class PromptRequest(BaseModel):
    text: str
    graph: Literal["podcast", "gazeta", "podcast-en"]
    nodes: list[str] | None = None
    language: str = "english"


def replace_reports(match):
    numbers_str = match.group(1)
    numbers = re.findall(r"\d+", numbers_str)
    first_three = numbers[:3]
    links = [f"[[report {num}#](/text/GRAPH_NAME/rep/{num})]" for num in first_three]
    return " ".join(links)


def format_response(resp: str, graph: str) -> str:
    new_text = re.sub(r"\[Data: Reports \(([^)]+)\)\]", replace_reports, resp)
    new_text = new_text.replace("GRAPH_NAME", graph)
    new_text = re.sub(r"\[Data: .+]", "", resp)
    return new_text


@app.post(path="/api/prompt")
async def prompt(
    req: PromptRequest,
    pg: asyncpg.Pool = Depends(get_connection_pool),
) -> PromptResponse:
    historical_response = await check_historical_prompt_response(
        pg, req.text, req.nodes
    )
    if historical_response:
        logger.info('msg="Got from cache"')
        return PromptResponse(response=format_response(historical_response, req.graph))
    else:
        search_engine = get_search_engine(req.graph, req.nodes, req.language)
        result = await search_engine.asearch(req.text)

        if isinstance(result.response, str):
            await save_prompt_response(
                pg, req.text, result.response, req.nodes, req.graph
            )
            return PromptResponse(response=format_response(result.response, req.graph))
        else:
            resp = format_response(result.response[0]["output"], req.graph)  # type: ignore
            await save_prompt_response(pg, req.text, resp, req.nodes, req.graph)
            return PromptResponse(response=resp)


@app.get(path="/api/prompt/history")
async def prompt_history(
    graph: str,
    pg: asyncpg.Pool = Depends(get_connection_pool),
) -> list[PromptHistory]:
    return [
        PromptHistory(prompt=x["prompt"], nodes=x["nodes"])
        for x in await get_prompts_history(pg, graph)
    ]


@app.get(path="/api/import-map")
async def get_graphs() -> list[dict]:
    return AVAILABLE_GRAPHS


@app.get(path="/api/graph/{id}")
def get_graph_data(id: str):
    try:
        import_map = AVAILABLE_GRAPHS

        graph_info = next((item for item in import_map if item["id"] == id), None)
        if not graph_info:
            raise HTTPException(status_code=404, detail="Path not found")

        graph_path = os.path.join(os.getcwd(), f"{graph_info['path']}/graph.json")
        with open(graph_path, "r", encoding="utf-8") as f:
            graph = json.load(f)

        return {"name": graph_info["name"], "graph": graph}

    except HTTPException:
        raise
    except Exception as error:
        print(error)
        raise HTTPException(status_code=500, detail="File read error")


class SaveGraphRequest(BaseModel):
    originalId: str
    graph: dict
    name: str | None = None


@app.post("/api/graph-save")
async def save_graph(request: SaveGraphRequest) -> dict:
    try:
        if not request.graph or not request.originalId:
            raise HTTPException(
                status_code=400, detail="Graph data and originalId are required"
            )

        logger.info(f"Found {len(AVAILABLE_GRAPHS)} graphs in import-map")

        original_graph = next(
            (item for item in AVAILABLE_GRAPHS if item["id"] == request.originalId),
            None,
        )
        if not original_graph:
            raise HTTPException(status_code=404, detail="Original graph not found")

        now = datetime.now()
        date_str = now.strftime("%Y%m%d")  # YYYYMMDD
        time_str = now.strftime("%H%M")  # HHMM
        base_name = request.name or original_graph["name"]
        new_name = f"{base_name}_{date_str}_{time_str}"
        new_id = f"{request.originalId}_{date_str}_{time_str}"
        new_path = f"data/graphs/{new_id}"

        graph_dir = os.path.join(os.getcwd(), new_path)
        logger.info(f"Creating graph directory: {graph_dir}")
        os.makedirs(graph_dir, exist_ok=True)

        graph_path = os.path.join(graph_dir, "graph.json")
        graph_content = json.dumps(request.graph, indent=2, ensure_ascii=False)
        with open(graph_path, "w", encoding="utf-8") as f:
            f.write(graph_content)
        logger.info(f"Graph saved to: {graph_path}")

        rep_path = os.path.join(graph_dir, "rep.json")
        with open(rep_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({}, indent=2))
        logger.info(f"Rep file created at: {rep_path}")

        new_graph_info = {"id": new_id, "name": new_name, "path": new_path}

        existing_graph = next(
            (item for item in AVAILABLE_GRAPHS if item["id"] == new_id), None
        )
        if existing_graph:
            logger.warning(f"Graph with id {new_id} already exists, skipping add")
        else:
            AVAILABLE_GRAPHS.append(new_graph_info)

        logger.info(f"Writing import-map.json with {len(AVAILABLE_GRAPHS)} graphs")
        logger.info("Import-map.json synced to disk")

        graph_exists = os.path.exists(graph_path)
        rep_exists = os.path.exists(rep_path)

        if not graph_exists or not rep_exists:
            logger.error(
                f"Graph files not found: graph={graph_exists}, rep={rep_exists}"
            )
            raise HTTPException(
                status_code=500, detail="Graph files were not created properly"
            )

        try:
            with open(graph_path, "r", encoding="utf-8") as f:
                test_graph = json.loads(f.read())
            if not test_graph or "nodes" not in test_graph:
                raise ValueError("Saved graph file is invalid")
            nodes_count = len(test_graph.get("nodes", []))
            logger.info(f"Verified: Graph file is valid with {nodes_count} nodes")
        except Exception as verify_error:
            logger.error(f"Failed to verify saved graph file: {verify_error}")
            raise HTTPException(
                status_code=500, detail="Failed to verify saved graph file"
            )

        logger.info(f"Graph saved successfully: {new_id} at {new_path}")
        logger.info(f"New graph info: {new_graph_info}")

        return {"success": True, "id": new_id, "name": new_name, "path": new_path}

    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Save graph error: {error}")
        raise HTTPException(status_code=500, detail=str(error))


if __name__ == "__main__":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    run(app, host="0.0.0.0", port=8000)

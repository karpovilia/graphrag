from fastapi import HTTPException
from loguru import logger
from yandex_cloud_ml_sdk import YCloudML
from settings import settings

import pandas as pd


from graphrag.query.indexer_adapters import (
    read_indexer_entities,
    read_indexer_reports,
)
from graphrag.query.structured_search.global_search.community_context import (
    GlobalCommunityContext,
)
from graphrag.query.structured_search.global_search.search import GlobalSearch
import tiktoken
import requests


from graphrag.query.structured_search.local_search.search import LocalSearch
from graphrag.query.structured_search.local_search.system_prompt import (
    LOCAL_SEARCH_SYSTEM_PROMPT,
)
from graphrag.query.structured_search.global_search.map_system_prompt import (
    MAP_SYSTEM_PROMPT,
)
from graphrag.query.structured_search.global_search.reduce_system_prompt import (
    REDUCE_SYSTEM_PROMPT,
)


def create_local_search_prompt_with_language(language: str | None) -> str:
    """Create a local search system prompt with language instruction."""
    base_prompt = LOCAL_SEARCH_SYSTEM_PROMPT
    if language:
        language_instruction = f"\n\n---Language Instruction---\n\nIMPORTANT: You must respond in {language}. All your responses, including descriptions, explanations, and any text you generate, must be written in {language}."
        # Insert language instruction after the Goal section
        prompt = base_prompt.replace(
            "---Goal---\n\nGenerate a response of the target length",
            f"---Goal---\n\nGenerate a response of the target length{language_instruction}",
        )
        return prompt
    return base_prompt


def create_map_system_prompt_with_language(language: str | None) -> str:
    """Create a map system prompt with language instruction."""
    base_prompt = MAP_SYSTEM_PROMPT
    if language:
        language_instruction = f"\n\n---Language Instruction---\n\nIMPORTANT: You must respond in {language}. All your responses, including descriptions, explanations, and any text you generate, must be written in {language}."
        # Insert language instruction after the Goal section
        prompt = base_prompt.replace(
            "---Goal---\n\nGenerate a response consisting of a list of key points",
            f"---Goal---\n\nGenerate a response consisting of a list of key points{language_instruction}",
        )
        return prompt
    return base_prompt


def create_reduce_system_prompt_with_language(language: str | None) -> str:
    """Create a reduce system prompt with language instruction."""
    base_prompt = REDUCE_SYSTEM_PROMPT
    if language:
        language_instruction = f"\n\n---Language Instruction---\n\nIMPORTANT: You must respond in {language}. All your responses, including descriptions, explanations, and any text you generate, must be written in {language}."
        # Insert language instruction after the Goal section
        prompt = base_prompt.replace(
            "---Goal---\n\nGenerate a response of the target length",
            f"---Goal---\n\nGenerate a response of the target length{language_instruction}",
        )
        return prompt
    return base_prompt


class YandexGPTEmbeddingLLM:
    def __init__(self):
        pass

    def embed(self, text):
        query_uri = f"emb://{settings.YANDEX_FOLDER_ID}/text-search-query/latest"

        embed_url = (
            "https://llm.api.cloud.yandex.net:443/foundationModels/v1/textEmbedding"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.YANDEX_TOKEN}",
            "x-folder-id": f"{settings.YANDEX_FOLDER_ID}",
        }

        query_data = {
            "modelUri": query_uri,
            "text": text,
        }
        res = requests.post(embed_url, json=query_data, headers=headers).json()

        return res["embedding"]


context_builder_params = {
    "use_community_summary": False,  # False means using full community reports. True means using community short summaries.
    "shuffle_data": True,
    "include_community_rank": True,
    "min_community_rank": 0,
    "community_rank_name": "rank",
    "include_community_weight": True,
    "community_weight_name": "occurrence weight",
    "normalize_community_weight": True,
    "max_tokens": 12_000,  # change this based on the token limit you have on your model (if you are using a model with 8k limit, a good setting could be 5000)
    "context_name": "Reports",
}

map_llm_params = {
    "max_tokens": 1000,
    "temperature": 0.0,
    "response_format": {"type": "json_object"},
}

reduce_llm_params = {
    "max_tokens": 2000,  # change this based on the token limit you have on your model (if you are using a model with 8k limit, a good setting could be 1000-1500)
    "temperature": 0.0,
}
local_context_params = {
    "text_unit_prop": 0.5,
    "community_prop": 0.1,
    "conversation_history_max_turns": 5,
    "conversation_history_user_turns_only": True,
    "top_k_mapped_entities": 10,
    "top_k_relationships": 10,
    "include_entity_rank": True,
    "include_relationship_weight": True,
    "include_community_rank": False,
    "return_candidate_context": False,
    # "embedding_vectorstore_key": EntityVectorStoreKey.ID,  # set this to EntityVectorStoreKey.TITLE if the vectorstore uses entity title as ids
    "max_tokens": 12_000,  # change this based on the token limit you have on your model (if you are using a model with 8k limit, a good setting could be 5000)
}

llm_params = {
    "max_tokens": 2_000,  # change this based on the token limit you have on your model (if you are using a model with 8k limit, a good setting could be 1000=1500)
    "temperature": 0.0,
}


PODCAST_ENTITY_DF = pd.read_parquet(settings.PODCAST.ENTITY_TABLE)
PODCAST_REPORT_DF = pd.read_parquet(settings.PODCAST.COMMUNITY_REPORT_TABLE)
PODCAST_ENTITY_EMBEDDING_DF = pd.read_parquet(settings.PODCAST.ENTITY_EMBEDDING_TABLE)
PODCAST_TEXT_UNITS_DF = pd.read_parquet(settings.PODCAST.TEXT_UNIT_TABLE)
PODCAST_COMMUNITIES_DF = pd.read_parquet(settings.PODCAST.COMMUNITY_TABLE)
PODCAST_COMMUNITIES_DF = PODCAST_COMMUNITIES_DF.rename(columns={"id": "community"})
PODCAST_RP_DF = pd.read_parquet(settings.PODCAST.RELATIONSHIP_TABLE)

GAZETA_ENTITY_DF = pd.read_parquet(settings.GAZETA.ENTITY_TABLE)
GAZETA_REPORT_DF = pd.read_parquet(settings.GAZETA.COMMUNITY_REPORT_TABLE)
GAZETA_ENTITY_EMBEDDING_DF = pd.read_parquet(settings.GAZETA.ENTITY_EMBEDDING_TABLE)
GAZETA_TEXT_UNITS_DF = pd.read_parquet(settings.GAZETA.TEXT_UNIT_TABLE)
GAZETA_COMMUNITIES_DF = pd.read_parquet(settings.GAZETA.COMMUNITY_TABLE)
GAZETA_RP_DF = pd.read_parquet(settings.GAZETA.RELATIONSHIP_TABLE)

TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")


class YandexGPT:
    def __init__(self):
        sdk = YCloudML(folder_id=settings.YANDEX_FOLDER_ID, auth=settings.YANDEX_TOKEN)
        self.model = sdk.models.completions(
            settings.YANDEX_MODEL, model_version=settings.YANDEX_MODEL_VERSION
        )

    def generate(self, prompt):
        response = self.model.run(prompt)
        result = {
            "output": response[0].text,
            "history": [],
        }

        return result

    async def agenerate(self, messages, *args, **kwargs):
        history = []
        for prompt in messages:
            prompt["text"] = prompt.pop("content")
            response = self.model.run(prompt)
            result = {
                "output": response[0].text,
                "history": [],
            }
            history.append(result)

        return history


def get_graph_data(
    graph: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    int,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    match graph:
        case "podcast" | "podcast-en":
            return (
                PODCAST_ENTITY_DF,
                PODCAST_REPORT_DF,
                PODCAST_ENTITY_EMBEDDING_DF,
                settings.PODCAST.COMMUNITY_LEVEL,
                PODCAST_COMMUNITIES_DF,
                PODCAST_TEXT_UNITS_DF,
                PODCAST_RP_DF,
            )
        case "gazeta":
            return (
                GAZETA_ENTITY_DF,
                GAZETA_REPORT_DF,
                GAZETA_ENTITY_EMBEDDING_DF,
                settings.GAZETA.COMMUNITY_LEVEL,
                GAZETA_COMMUNITIES_DF,
                GAZETA_TEXT_UNITS_DF,
                GAZETA_RP_DF,
            )
        case _:
            logger.error('msg="Unknown graph"')
            raise HTTPException(status_code=404, detail="graph not found")


def get_search_engine(
    graph: str, nodes: list[str] | None, language: str | None = None
) -> GlobalSearch | LocalSearch:
    logger.info('msg="New prompting"')
    (
        entity_df,
        report_df,
        entity_embedding_df,
        community_level,
        communities_df,
        text_units_df,
        rp_df,
    ) = get_graph_data(graph)

    if nodes:
        logger.info(f'msg="Nodes selected" {nodes=}')
        # relationships = read_indexer_relationships(rp_df)
        # reports = read_indexer_reports(report_df, communities_df, community_level)
        # text_units = read_indexer_text_units(text_units_df)
        # _entities = read_indexer_entities(
        #     entity_df[entity_df.title.isin(nodes)],  # type: ignore
        #     entity_embedding_df,
        #     community_level,
        # )
        #
        # description_embedding_store = _get_embedding_description_store(
        #     entities=_entities,
        # )
        # context_builder = LocalSearchMixedContext(
        #     community_reports=reports,
        #     text_units=text_units,
        #     entities=_entities,
        #     relationships=relationships,
        #     entity_text_embeddings=description_embedding_store,
        #     text_embedder=YandexGPTEmbeddingLLM(),  # type: ignore
        #     token_encoder=TOKEN_ENCODER,
        # )
        # custom_system_prompt = create_local_search_prompt_with_language(language)
        # search_engine = LocalSearch(
        #     llm=YandexGPT(),  # type: ignore
        #     context_builder=context_builder,
        #     token_encoder=TOKEN_ENCODER,
        #     llm_params=llm_params,
        #     context_builder_params=local_context_params,
        #     response_type="multiple paragraphs",  # free form text describing the response type and format, can be anything, e.g. prioritized list, single paragraph, multiple paragraphs, multiple-page report
        #     system_prompt=custom_system_prompt,
        # )

        global_reports = read_indexer_reports(
            report_df,
            entity_df[entity_df.title.isin(nodes)],  # type: ignore
            community_level,
        )
        global_entities = read_indexer_entities(
            entity_df[entity_df.title.isin(nodes)],  # type: ignore
            entity_embedding_df,  # type: ignore
            community_level,
        )
        global_context_builder = GlobalCommunityContext(
            community_reports=global_reports,
            entities=global_entities,  # default to None if you don't want to use community weights for ranking
            token_encoder=TOKEN_ENCODER,
        )
        custom_map_prompt = create_map_system_prompt_with_language(language)
        custom_reduce_prompt = create_reduce_system_prompt_with_language(language)
        global_search_engine = GlobalSearch(
            context_builder=global_context_builder,
            folder_id=settings.YANDEX_FOLDER_ID,
            token=settings.YANDEX_TOKEN,
            token_encoder=TOKEN_ENCODER,
            max_data_tokens=12_000,
            map_llm_params=map_llm_params,
            reduce_llm_params=reduce_llm_params,
            context_builder_params=context_builder_params,
            response_type="multiple paragraphs",
            map_system_prompt=custom_map_prompt,
            reduce_system_prompt=custom_reduce_prompt,
        )

        return global_search_engine

    else:
        global_reports = read_indexer_reports(
            report_df,
            entity_df,  # type: ignore
            community_level,
        )
        global_entities = read_indexer_entities(
            entity_df,  # type: ignore
            entity_embedding_df,  # type: ignore
            community_level,
        )
        global_context_builder = GlobalCommunityContext(
            community_reports=global_reports,
            entities=global_entities,  # default to None if you don't want to use community weights for ranking
            token_encoder=TOKEN_ENCODER,
        )
        custom_map_prompt = create_map_system_prompt_with_language(language)
        custom_reduce_prompt = create_reduce_system_prompt_with_language(language)
        global_search_engine = GlobalSearch(
            context_builder=global_context_builder,
            folder_id=settings.YANDEX_FOLDER_ID,
            token=settings.YANDEX_TOKEN,
            token_encoder=TOKEN_ENCODER,
            max_data_tokens=12_000,
            map_llm_params=map_llm_params,
            reduce_llm_params=reduce_llm_params,
            context_builder_params=context_builder_params,
            response_type="multiple paragraphs",
            map_system_prompt=custom_map_prompt,
            reduce_system_prompt=custom_reduce_prompt,
        )

        return global_search_engine

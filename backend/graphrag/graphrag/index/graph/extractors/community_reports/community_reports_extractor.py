# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""A module containing 'CommunityReportsResult' and 'CommunityReportsExtractor' models."""

import logging
import traceback
from dataclasses import dataclass
from typing import Any

from graphrag.index.typing import ErrorHandlerFn
from graphrag.llm import CompletionLLM

from .prompts import COMMUNITY_REPORT_PROMPT
from yandex_cloud_ml_sdk import YCloudML
import json
import os

log = logging.getLogger(__name__)

current_dir = os.getcwd()
parent_dir = os.path.abspath(os.path.join(current_dir, "graphrag"))
file_path = os.path.join(parent_dir, "api_key.json")

try:
    folder_id = os.getenv("YANDEX_FOLDER_ID")
    token = os.getenv("YANDEX_TOKEN")
    model_name = os.getenv("YANDEX_MODEL_NAME")
    model_version = os.getenv("YANDEX_MODEL_VERSION")

except FileNotFoundError:
    print("Файл не найден.")
except json.JSONDecodeError:
    print("Ошибка декодирования JSON.")


@dataclass
class CommunityReportsResult:
    """Community reports result class definition."""

    output: str
    structured_output: dict


class CommunityReportsExtractor:
    """Community reports extractor class definition."""

    _llm: CompletionLLM
    _input_text_key: str
    _extraction_prompt: str
    _output_formatter_prompt: str
    _on_error: ErrorHandlerFn
    _max_report_length: int

    def __init__(
        self,
        llm_invoker: CompletionLLM,
        input_text_key: str | None = None,
        extraction_prompt: str | None = None,
        on_error: ErrorHandlerFn | None = None,
        max_report_length: int | None = None,
    ):
        """Init method definition."""
        self._llm = llm_invoker
        self._input_text_key = input_text_key
        #  or "input_text"
        self._extraction_prompt = extraction_prompt or COMMUNITY_REPORT_PROMPT
        self._on_error = on_error or (lambda _e, _s, _d: None)
        self._max_report_length = max_report_length or 1500

    async def __call__(self, inputs: dict[str, Any]):
        """Call method definition."""
        output = None
        try:
            sdk = YCloudML(folder_id=folder_id, auth=token)
            new_model = sdk.models.completions(model_name, model_version=model_version)

            input_text = inputs["input_text_key"]

            prompt = f"""

            You are an AI assistant that helps a human analyst to perform general information discovery. Information discovery is the process of identifying and assessing relevant information associated with certain entities (e.g., organizations and individuals) within a network.

            # Goal
            Write a comprehensive report of a community, given a list of entities that belong to the community as well as their relationships and optional associated claims. The report will be used to inform decision-makers about information associated with the community and their potential impact. The content of this report includes an overview of the community's key entities, their legal compliance, technical capabilities, reputation, and noteworthy claims.

            # Report Structure

            The report should include the following sections:

            - TITLE: community's name that represents its key entities - title should be short but specific. When possible, include representative named entities in the title.
            - SUMMARY: An executive summary of the community's overall structure, how its entities are related to each other, and significant information associated with its entities.
            - IMPACT SEVERITY RATING: a float score between 0-10 that represents the severity of IMPACT posed by entities within the community.  IMPACT is the scored importance of a community.
            - RATING EXPLANATION: Give a single sentence explanation of the IMPACT severity rating.
            - DETAILED FINDINGS: A list of 5-10 key insights about the community. Each insight should have a short summary followed by multiple paragraphs of explanatory text grounded according to the grounding rules below. Be comprehensive.

            Return output as a well-formed JSON-formatted string with the following format:
                {{
                    "title": <report_title>,
                    "summary": <executive_summary>,
                    "rating": <impact_severity_rating>,
                    "rating_explanation": <rating_explanation>,
                    "findings": [
                        {{
                            "summary":<insight_1_summary>,
                            "explanation": <insight_1_explanation>
                        }},
                        {{
                            "summary":<insight_2_summary>,
                            "explanation": <insight_2_explanation>
                        }}
                    ]
                }}

            Do not use the symbol " inside the dictionary values

            # Grounding Rules

            Points supported by data should list their data references as follows:

            "This is an example sentence supported by multiple data references [Data: <dataset name> (record ids); <dataset name> (record ids)]."

            Do not list more than 5 record ids in a single reference. Instead, list the top 5 most relevant record ids and add "+more" to indicate that there are more.

            For example:
            "Person X is the owner of Company Y and subject to many allegations of wrongdoing [Data: Reports (1), Entities (5, 7); Relationships (23); Claims (7, 2, 34, 64, 46, +more)]."

            where 1, 5, 7, 23, 2, 34, 46, and 64 represent the id (not the index) of the relevant data record.

            Do not include information where the supporting evidence for it is not provided.


            # Example Input
            -----------
            Text:

            Entities

            id,entity,description
            5,VERDANT OASIS PLAZA,Verdant Oasis Plaza is the location of the Unity March
            6,HARMONY ASSEMBLY,Harmony Assembly is an organization that is holding a march at Verdant Oasis Plaza

            Relationships

            id,source,target,description
            37,VERDANT OASIS PLAZA,UNITY MARCH,Verdant Oasis Plaza is the location of the Unity March
            38,VERDANT OASIS PLAZA,HARMONY ASSEMBLY,Harmony Assembly is holding a march at Verdant Oasis Plaza
            39,VERDANT OASIS PLAZA,UNITY MARCH,The Unity March is taking place at Verdant Oasis Plaza
            40,VERDANT OASIS PLAZA,TRIBUNE SPOTLIGHT,Tribune Spotlight is reporting on the Unity march taking place at Verdant Oasis Plaza
            41,VERDANT OASIS PLAZA,BAILEY ASADI,Bailey Asadi is speaking at Verdant Oasis Plaza about the march
            43,HARMONY ASSEMBLY,UNITY MARCH,Harmony Assembly is organizing the Unity March

            Output:
            {{
                "title": "Verdant Oasis Plaza and Unity March",
                "summary": "The community revolves around the Verdant Oasis Plaza, which is the location of the Unity March. The plaza has relationships with the Harmony Assembly, Unity March, and Tribune Spotlight, all of which are associated with the march event.",
                "rating": 5.0,
                "rating_explanation": "The impact severity rating is moderate due to the potential for unrest or conflict during the Unity March.",
                "findings": [
                    {{
                        "summary": "Verdant Oasis Plaza as the central location",
                        "explanation": "Verdant Oasis Plaza is the central entity in this community, serving as the location for the Unity March. This plaza is the common link between all other entities, suggesting its significance in the community. The plaza's association with the march could potentially lead to issues such as public disorder or conflict, depending on the nature of the march and the reactions it provokes. [Data: Entities (5), Relationships (37, 38, 39, 40, 41,+more)]"
                    }},
                    {{
                        "summary": "Harmony Assembly's role in the community",
                        "explanation": "Harmony Assembly is another key entity in this community, being the organizer of the march at Verdant Oasis Plaza. The nature of Harmony Assembly and its march could be a potential source of threat, depending on their objectives and the reactions they provoke. The relationship between Harmony Assembly and the plaza is crucial in understanding the dynamics of this community. [Data: Entities(6), Relationships (38, 43)]"
                    }},
                    {{
                        "summary": "Unity March as a significant event",
                        "explanation": "The Unity March is a significant event taking place at Verdant Oasis Plaza. This event is a key factor in the community's dynamics and could be a potential source of threat, depending on the nature of the march and the reactions it provokes. The relationship between the march and the plaza is crucial in understanding the dynamics of this community. [Data: Relationships (39)]"
                    }},
                    {{
                        "summary": "Role of Tribune Spotlight",
                        "explanation": "Tribune Spotlight is reporting on the Unity March taking place in Verdant Oasis Plaza. This suggests that the event has attracted media attention, which could amplify its impact on the community. The role of Tribune Spotlight could be significant in shaping public perception of the event and the entities involved. [Data: Relationships (40)]"
                    }}
                ]
            }}


            # Real Data

            Use the following text for your answer. Do not make anything up in your answer.

            Text:
            {input_text}

            The report should include the following sections:

            - TITLE: community's name that represents its key entities - title should be short but specific. When possible, include representative named entities in the title.
            - SUMMARY: An executive summary of the community's overall structure, how its entities are related to each other, and significant information associated with its entities.
            - IMPACT SEVERITY RATING: a float score between 0-10 that represents the severity of IMPACT posed by entities within the community.  IMPACT is the scored importance of a community.
            - RATING EXPLANATION: Give a single sentence explanation of the IMPACT severity rating.
            - DETAILED FINDINGS: A list of 5-10 key insights about the community. Each insight should have a short summary followed by multiple paragraphs of explanatory text grounded according to the grounding rules below. Be comprehensive.

            Return output as a well-formed JSON-formatted string with the following format:
                {{
                    "title": <report_title>,
                    "summary": <executive_summary>,
                    "rating": <impact_severity_rating>,
                    "rating_explanation": <rating_explanation>,
                    "findings": [
                        {{
                            "summary":<insight_1_summary>,
                            "explanation": <insight_1_explanation>
                        }},
                        {{
                            "summary":<insight_2_summary>,
                            "explanation": <insight_2_explanation>
                        }}
                    ]
                }}

            # Grounding Rules

            Points supported by data should list their data references as follows:

            "This is an example sentence supported by multiple data references [Data: <dataset name> (record ids); <dataset name> (record ids)]."

            Do not list more than 5 record ids in a single reference. Instead, list the top 5 most relevant record ids and add "+more" to indicate that there are more.

            For example:
            "Person X is the owner of Company Y and subject to many allegations of wrongdoing [Data: Reports (1), Entities (5, 7); Relationships (23); Claims (7, 2, 34, 64, 46, +more)]."

            where 1, 5, 7, 23, 2, 34, 46, and 64 represent the id (not the index) of the relevant data record.

            Do not include information where the supporting evidence for it is not provided.

            Output:


            """

            # prompt = self._extraction_prompt.replace('input_text', inputs[self._input_text_key])

            response = new_model.run(prompt)

            result = {
                "output": response[0].text,
                "history": [],
            }

            def normalize_json_string(json_string):
                json_string = json_string.strip("```")
                normalized_string = json.loads(json_string)
                return normalized_string

            # output = json.loads(result['output'])
            output = normalize_json_string(result["output"])
            # output = response.json or {}
        except Exception as e:
            log.exception("error generating community report")
            self._on_error(e, traceback.format_exc(), None)
            output = {}

        text_output = self._get_text_output(output)
        return CommunityReportsResult(
            structured_output=output,
            output=text_output,
        )

    def _get_text_output(self, parsed_output: dict) -> str:
        title = parsed_output.get("title", "Report")
        summary = parsed_output.get("summary", "")
        findings = parsed_output.get("findings", [])

        def finding_summary(finding: dict):
            if isinstance(finding, str):
                return finding
            return finding.get("summary")

        def finding_explanation(finding: dict):
            if isinstance(finding, str):
                return ""
            return finding.get("explanation")

        report_sections = "\n\n".join(
            f"## {finding_summary(f)}\n\n{finding_explanation(f)}" for f in findings
        )
        return f"# {title}\n\n{summary}\n\n{report_sections}"

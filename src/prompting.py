from __future__ import annotations
from typing import Optional, List
from pathlib import Path
import sqlite3
from . import api
import logging


######


def check_token_and_add_to_prompt(
    constructed_prompt: str,
    added_text: str,
    existing_token_count: Optional[int] = None,
    added_text_token_count: Optional[int] = None,
    context_length: Optional[int] = 2048,
    append: Optional[bool] = True,
):
    existing_token_count = existing_token_count or api.count_tokens(constructed_prompt)
    added_text_token_count = added_text_token_count or api.count_tokens(added_text)

    token_count = existing_token_count + added_text_token_count

    if token_count <= context_length:
        return (
            (constructed_prompt + added_text, token_count, True)
            if append
            else (added_text + constructed_prompt, token_count, True)
        )
    else:
        return (constructed_prompt, existing_token_count, False)


def construct_prechat_prompt(character_name: str, character_context: str, config: dict):
    preamble_prompt = config.get("preamble_prompt", "")
    persona_prompt = config.get("persona_prompt", "## Persona")

    if preamble_prompt:
        preamble_prompt = preamble_prompt.replace("{{user}}", "You").replace(
            "{{char}}", character_name
        )

    persona_prompt = f"{persona_prompt}\n{character_context}"

    constructed_prompt = f"{preamble_prompt}\n{persona_prompt}"

    return constructed_prompt


def prepare_message(name: str, message: str, add_hashes_to_conversation: bool = True):
    prefix = "### " if add_hashes_to_conversation else ""
    return f"\n{prefix}{name}: {message}"


def prepare_character_prompt(
    character,
    message_history,
    context_length,
    config,
    scenario: Optional[str] = "",
    add_hashes_to_convo: bool = True,
):
    try:
        prefix = "### " if add_hashes_to_convo else ""

        constructed_prompt = construct_prechat_prompt(
            character["name"], character["persona"], config
        )

        character_scenario = (
            f'\n{character["scenario"]}' if character["scenario"] else ""
        )

        total_scenario = scenario + character_scenario
        logging.debug(total_scenario)

        if scenario != "" or character["scenario"]:
            constructed_end_prompt = f"{config.get('scenario_prompt', '## Scenario')}{total_scenario}\n{config.get('epilogue_prompt', '## Chat')}"
            logging.debug(constructed_end_prompt)
            token_count = api.count_tokens(
                constructed_prompt
                + f"\n{prefix}{character['name']}:"
                + f"{config.get('scenario_prompt', '## Scenario')}\n{total_scenario}\n{config.get('epilogue_prompt', '## Chat')}"
            )
            logging.debug(token_count)
        else:
            constructed_end_prompt = f"\n{config.get('epilogue_prompt', '## Chat')}"
            token_count = api.count_tokens(
                constructed_prompt
                + config.get("epilogue_prompt", "## Chat")
                + f"\n{prefix}{character['name']}:"
            )

        message_prompt = ""

        authors = set()
        x = 0
        while token_count < context_length and x < len(message_history) + 1:
            if x < len(message_history):
                current_message = message_history[x]

                if not current_message["message_content"].isspace():
                    prepared_message = prepare_message(
                        current_message["author"],
                        current_message["message_content"],
                        add_hashes_to_convo,
                    )
                    (
                        message_prompt,
                        token_count,
                        added_message,
                    ) = check_token_and_add_to_prompt(
                        message_prompt,
                        f"{prepared_message}",
                        token_count,
                        None,
                        context_length,
                        True,
                    )
                    if added_message:
                        authors.add(f"\n{current_message['author']}")

            elif x == len(message_history) and character["example_conversation"]:
                example_conversation = (
                    f"\n\n{config.get('example_conversation_prompt', '## Example conversation')}\n"
                    + character["example_conversation"]
                    + "\n"
                )

                token_count += api.count_tokens(example_conversation)
                if token_count < context_length:
                    message_prompt = (
                        example_conversation + constructed_end_prompt + message_prompt
                    )
                # else: break out of loop
            elif x == len(message_history):
                message_prompt = constructed_end_prompt + message_prompt

            x = x + 1

        constructed_prompt += message_prompt
        constructed_prompt += f"\n{prefix}{character['name']}:"
        stopping_strings = list(authors)
        return (
            constructed_prompt,
            stopping_strings,
        )
    except Exception as e:
        raise Exception(f"Error in prompt creation: {e}")

from __future__ import annotations
from pathlib import Path
import logging
from typing import Optional
import os, yaml, json, glob
from . import db


def get_dict_from_filepath(filepath: Optional[str]):
    if filepath and os.path.exists(filepath):
        contents = open(filepath, "r", encoding="utf-8").read()
        ext = os.path.splitext(filepath)
        config = json.loads(contents) if ext == "json" else yaml.safe_load(contents)
        return config
    else:
        return None


def load_config(filepath: str):
    config = get_dict_from_filepath(filepath)
    if not config:
        logging.error(f"Configuration file not found at {filepath}")
        raise Exception(f"Configuration file not found at {filepath}")

    discord_token = config.get("DISCORD_TOKEN")

    prompt_config = get_dict_from_filepath(config.get("prompt_preset_path"))

    max_turns = config.get("max_rounds_in_continuation", 5)
    max_turns = max_turns if max_turns > 0 else 5

    generate_params = (
        get_dict_from_filepath(config.get("generation_parameters_preset_path")) or {}
    )

    generate_params["truncation_length"] = config.get("context_length", 2046)

    config = {
        "context_length": config.get("context_length", 2046),
        "add_hashes_to_conversation": config.get("add_hashes_to_conversation", False),
        "prompt_config": prompt_config,
        "character_directories": config.get("character_directories"),
        "max_rounds_in_continuation": max_turns,
        "default_character": config.get("default_character", "CadLLM"),
        "reply_to_other_bots": config.get("reply_to_other_bots", False),
        "generate_params": generate_params,
        "max_characters_in_group_chat": config.get(
            "max_characters_in_group_chat", None
        ),
    }

    return discord_token, config


def load_all_characters_in_filepath(filepath: str, cursor: any, logging: any):
    character_filepaths = []
    for file in glob.glob(os.path.join(filepath, f"*.yaml")):
        load_or_update_character_data_from_file(file, cursor, logging)
        character_filepaths.append(Path(file).stem)
    return character_filepaths


#######
def load_character_data_from_file(filepath: str):
    file_contents = open(filepath, "r", encoding="utf-8").read()
    ext = os.path.splitext(filepath)
    data = json.loads(file_contents) if ext == "json" else yaml.safe_load(file_contents)

    charname = data.get("name")
    example_convo = data.get("example_dialogue") or data.get("example_conversation")
    if example_convo:
        example_convo = example_convo.replace("{{user}}", "You").replace(
            "{{char}}", charname
        )

    return {
        "filename": Path(filepath).stem,
        "name": charname,
        "greeting": data.get("greeting"),
        "context": data.get("context") or data.get("persona"),
        "example_conversation": example_convo,
    }


######
def load_or_update_character_data_from_file(filepath: str, cursor: any, logging: any):
    try:
        chardata = load_character_data_from_file(filepath)
        db.register_or_update_character_in_database(
            chardata["name"],
            chardata["filename"],
            chardata["context"],
            cursor,
            chardata["example_conversation"],
            chardata["greeting"],
        )
    except Exception as e:
        # logging goes here
        logging.error(f"Error loading or updating character: {e}")

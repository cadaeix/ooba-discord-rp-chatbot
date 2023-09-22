from __future__ import annotations
import asyncio
import random
import logging
import logging.handlers
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from . import api, db, loading, prompting


async def send_long_message(channel, message_text):
    """Splits a longer message into parts, making sure code blocks are maintained"""
    codeblock_index = message_text.find("```")
    if codeblock_index >= 0:
        closing_codeblock_index = message_text.find("```", codeblock_index + 3)

    if (
        len(message_text) <= 2000
        or codeblock_index == -1
        or closing_codeblock_index == -1
    ):
        await channel.send(f"{message_text}")
    else:
        chunk_text = message_text[0 : closing_codeblock_index + 3]
        await channel.send(f"{chunk_text}")
        await send_long_message(channel, message_text[closing_codeblock_index + 3 :])


class QueueRequest:
    def __init__(self, channel_id: int, author_id: int):
        self.channel_id = channel_id
        self.author_id = author_id

    async def enqueue_request():
        ...

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        ...


class GenericGenerationRequest:
    def __init__(
        self,
        channel_id: int,
        author_id: int,
        message_content: str,
        should_send_message: bool,
        previous_message_if_edit: Optional[any] = None,
    ):
        super().__init__(channel_id, author_id)
        self.message_content = message_content
        self.should_send_message = should_send_message
        self.previous_message_if_edit = previous_message_if_edit

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        message = self.message_content.replace("\\n", "\n")
        params = config.get("generate_params", {})
        params["auto_max_new_tokens"] = True
        response = await api.generate_text(message, params)
        if self.should_send_message:
            channel = await client.fetch_channel(int(self.channel_id))
            await send_long_message(channel, f"**{message}** {response}")
        elif self.previous_message_if_edit:
            await self.previous_message_if_edit.edit(
                content=f"{self.previous_message_if_edit.content}{response}"
            )


class GenericDatabaseRequest(QueueRequest):
    def __init__(
        self,
        channel_id: int,
        author_id: int,
        database_func: any,
        func_kwargs: any,
        success_embed: dict,
        failure_embed: dict,
    ):
        super().__init__(channel_id, author_id)

        # handle checking if character exists before this
        self.database_function = database_func
        self.func_kwargs = func_kwargs
        self.success_embed = success_embed
        self.failure_embed = failure_embed

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        channel = await client.fetch_channel(int(self.channel_id))
        try:
            self.database_function(**self.func_kwargs, cursor=cursor)
            conn.commit()
            await channel.send(embed=discord.Embed().from_dict(self.success_embed))
        except Exception as e:
            conn.rollback()
            self.failure_embed["description"] = self.failure_embed[
                "description"
            ].replace("{{e}}", e)
            await channel.send(embed=discord.Embed().from_dict(self.failure_embed))


class ClearRequest(QueueRequest):
    def __init__(
        self,
        channel_id: int,
        author_id: int,
        clear_history: bool,
        clear_activated_characters: bool,
        clear_channel_scenario: bool,
        clear_character_scenarios: bool,
    ):
        super().__init__(channel_id, author_id)

        if (
            clear_history
            or clear_activated_characters
            or clear_channel_scenario
            or clear_character_scenarios
        ):
            self.clear_history = clear_history
            self.clear_activated_characters = clear_activated_characters
            self.clear_channel_scenario = clear_channel_scenario
            self.clear_character_scenarios = clear_character_scenarios
        else:
            raise Exception("Clear request sent without clearing anything.")

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        channel = await client.fetch_channel(int(self.channel_id))
        try:
            things_reset = []

            if self.clear_history:
                db.reset_memory_for_current_channel(self.channel_id, cursor)
                things_reset.append(
                    "Character message history for current channel cleared"
                )

            if self.clear_activated_characters:
                db.deactivate_all(self.channel_id, cursor)
                things_reset.append("All characters in current channel deactivated")

            if self.clear_channel_scenario:
                db.add_scenario_to_current_room(self.channel_id, None, cursor)
                things_reset.append("Channel scenario for current channel cleared")

            if self.clear_character_scenarios and not self.clear_activated_characters:
                db.reset_all_active_character_scenarios(self.channel_id, cursor)
                things_reset.append(
                    "All character scenarios for current channel cleared"
                )

            conn.commit()

            success_embed_description = "\n• " + "\n• ".join(things_reset)

            await channel.send(
                embed=discord.Embed().from_dict(
                    {
                        "title": f"Reset the following:",
                        "description": success_embed_description,
                    }
                )
            )

        except Exception as e:
            await channel.send(
                embed=discord.Embed().from_dict(
                    {
                        "title": f"Could not complete clear command.",
                        "description": f"Error: {e}",
                    }
                )
            )


class ActivateRequest(QueueRequest):
    def __init__(
        self,
        channel_id: int,
        author_id: int,
        character_name: any,
        greeting: bool,
        scenario: Optional[str],
        negative_prompt: Optional[str],
    ):
        super().__init__(channel_id, author_id)

        # handle checking if character exists before this
        self.character_name = character_name
        self.greeting = greeting
        self.scenario = scenario
        self.negative_prompt = negative_prompt

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        channel = await client.fetch_channel(int(self.channel_id))
        try:
            if config.get("max_characters_in_group_chat"):
                character_data = db.get_active_character_data_per_room(
                    self.channel_id, cursor
                )
                character_names = list(i["name"] for i in character_data)
                if (
                    len(character_data) >= config.get("max_characters_in_group_chat")
                    and self.character_name not in character_names
                ):
                    raise Exception(
                        f"Cannot exceed configured limit of active characters per channel set at {config.get('max_characters_in_group_chat')}."
                    )

            db.set_active_character_per_room(
                self.character_name,
                self.channel_id,
                cursor,
                True,
                self.scenario,
                self.negative_prompt,
            )
            conn.commit()
            logging.debug("character activated")
            character_info = db.retrieve_character_information_by_filename(
                self.character_name, cursor
            )
            logging.debug(character_info)
            # conn.close()
            embed_description = (
                f"Scenario for this character set: {self.scenario}"
                if self.scenario
                else ""
            )

            await channel.send(
                embed=discord.Embed().from_dict(
                    {
                        "title": f"{self.character_name} now active in this channel.",
                        "description": embed_description,
                    }
                )
            )
            logging.info(f"{self.character_name} activated for {self.channel_id}")
            if self.greeting and character_info[0]["greeting"]:
                await send_long_message(
                    channel,
                    f"**{character_info[0]['name']}**: {character_info[0]['greeting']}",
                )
                db.save_message(
                    character_info[0]["greeting"],
                    character_info[0]["name"],
                    self.channel_id,
                    None,
                    cursor,
                    True,
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            embed_message = {
                "title": f"Failed to activate {self.character_name}.",
                "description": f"Error: {e}",
            }
            await channel.send(embed=discord.Embed().from_dict(embed_message))
            logging.error(e)


class ChatGenerationRequest(QueueRequest):
    def __init__(
        self,
        channel_id: int,
        author_id: int,
        message_id: id,
        author_display_name: str,
        message_content: str,
        is_continuation: Optional[bool] = False,
    ):
        super().__init__(channel_id, author_id)

        self.author_display_name = author_display_name
        self.message_content = message_content
        self.message_id = message_id
        self.is_continuation = is_continuation

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        # try:
        channel = await client.fetch_channel(int(self.channel_id))
        prompt_config = config.get("prompt_config", {})
        if not self.is_continuation:
            db.save_user_message_to_history(
                self.author_id,
                self.channel_id,
                self.message_id,
                self.message_content,
                self.author_display_name,
                cursor,
                conn,
            )
            conn.commit()

        chardata = db.get_active_character_data_per_room(self.channel_id, cursor)
        if len(chardata) < 1:  # activate character if there isn't any
            db.set_active_character_per_room(
                config.get("default_character"), self.channel_id, cursor, True, None
            )
            await channel.send(
                embed=discord.Embed().from_dict(
                    {
                        "title": f"{config.get('default_character')} now active in this channel.",
                        "description": "",
                    }
                )
            )
            chardata = db.get_active_character_data_per_room(self.channel_id, cursor)

        if (not self.is_continuation and len(chardata) > 1) or (
            self.is_continuation and len(chardata) > 2
        ):  # eh, if its a continuation with just two characters, dont permute order
            random.shuffle(chardata)

        generation_params = config.get("generate_params", {})
        prelim_stopping_strings = [
            "\n##",
            "</s>",
            "<|",
            "\n\n\n",
            "\n#",
            "\nUser:",
            "\nYou:",
        ] + generation_params.get("stopping_strings", [])

        talking_characters = []
        for character in chardata:
            prelim_stopping_strings.append(f"\n{character['name']:}")
            if (
                len(chardata) > 1
                and self.message_content
                and any(
                    word in self.message_content.lower()
                    for word in character["name"].lower().split()
                )
            ):  # characters who are mentioned in the message talk first
                talking_characters = [character] + talking_characters
            else:  # insert chance for character to not talk here? this is also if there's only one character
                talking_characters.append(character)

        scenario = db.get_scenario_from_current_room(self.channel_id, cursor) or ""
        for character in talking_characters:
            async with channel.typing():
                message_history = db.get_message_history_from_channel(
                    self.channel_id, cursor
                )
                (
                    constructed_prompt,
                    additional_stopping_strings,
                ) = prompting.prepare_character_prompt(
                    character,
                    message_history,
                    config.get("context_length", 2046),
                    prompt_config,
                    scenario,
                    config.get("add_hashes_to_conversation", False),
                )
                stopping_strings = list(
                    set(additional_stopping_strings + prelim_stopping_strings)
                )
                logging.debug(constructed_prompt)
                logging.debug(stopping_strings)
                params = generation_params
                params["negative_prompt"] = (
                    character["negative_prompt"] or ""
                ) + params.get("negative_prompt", "")
                params["stopping_strings"] = stopping_strings
                logging.debug(params)

                response = await api.generate_text(
                    constructed_prompt,
                    params,
                )
                response = response.strip()
                logging.info(f"Reply generated: {response}")
                if not response.isspace():  # if something was generated
                    await send_long_message(
                        channel, f"**{character['name']}**: {response}"
                    )
                    db.save_message(
                        response,
                        character["name"],
                        self.channel_id,
                        None,
                        cursor,
                        True,
                    )
                conn.commit()

        # except Exception as e:
        #     raise Exception(f"Generation request error: {e}")


class SaveAndSendMessageRequest(QueueRequest):
    def __init__(
        self,
        channel_id: int,
        author_id: int,
        message_author: str,
        message_content: str,
        display_author: bool,
    ):
        super().__init__(channel_id, author_id)
        self.message_author = message_author
        self.message_content = message_content
        self.display_author = display_author

    async def attend_request(self, cursor: any, conn: any, config: any, client: any):
        channel = await client.fetch_channel(int(self.channel_id))
        async with channel.typing():
            message_to_send = (
                f"**{self.message_author}**: {self.message_content}"
                if self.display_author
                else self.message_content
            )
            await send_long_message(
                channel,
                f"{message_to_send}",
            )
            db.save_message(
                self.message_content,
                self.message_author,
                self.channel_id,
                None,
                cursor,
                True,
            )
            conn.commit()

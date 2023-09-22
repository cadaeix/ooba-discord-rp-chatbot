from __future__ import annotations
import asyncio
import logging
import logging.handlers
import discord
import queue
import inspect
from discord import app_commands
from discord.ext import commands
from typing import List, Optional

from src import api, db, loading, queuing

TOKEN, CONFIG = loading.load_config("config.yaml")


def update_generation_params(new_config: dict):
    global CONFIG
    CONFIG["generate_params"] = new_config


# prepare logs
logging.basicConfig(
    format="%(levelname)s [%(asctime)s]: %(message)s (Line: %(lineno)d in %(funcName)s, %(filename)s )",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)

handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
handler = logging.handlers.RotatingFileHandler(
    filename="discord.log",
    encoding="utf-8",
    maxBytes=32 * 1024 * 1024,  # 32 MiB
    backupCount=5,  # Rotate through 5 files
)

# start db
conn, cursor = db.connect_to_db()

# Load Bot
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix=".", intents=intents, help_command=None)
client.remove_command("help")

visible_characters = []
request_queue = queue.Queue()


###


# TODO: no actual filepath existing checking yet lol


def load_all_characters_and_return_visible_ones(filepaths: List[dict], cursor: any):
    visible_characters = []
    for fp in filepaths:
        if isinstance(fp, dict):
            charlist = loading.load_all_characters_in_filepath(
                fp.get("filepath") if isinstance(fp, dict) else fp, cursor, logging
            )
            if fp.get("visible"):
                visible_characters = visible_characters + charlist
        elif isinstance(fp, str):
            charlist = loading.load_all_characters_in_filepath(
                fp.get("filepath"), cursor, logging
            )
            visible_characters.append(charlist)
    return visible_characters


def refresh_characters(ctx, cursor):
    ctx.bot.visible_characters = load_all_characters_and_return_visible_ones(
        CONFIG.get("character_directories"), cursor
    )


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


def check_number_of_messages_for_author_in_queue(message):
    user = message.author.id
    user_list_in_que = list(i.author_id for i in list(request_queue.queue))
    logging.debug(user_list_in_que)
    logging.debug(user_list_in_que.count(user))
    return user_list_in_que.count(user)


async def attend_chatbot_request(client):
    while True:
        if not request_queue.empty():
            request = request_queue.get()
            logging.debug(request)
            # try:
            await request.attend_request(cursor, conn, CONFIG, client)
            # except Exception as e:
            #     logging.info(f"Queued request went wrong, {e}")
        else:
            await asyncio.sleep(1)


@client.event
async def on_ready():
    # conn, cursor = db.connect_to_db()
    db.setup_database(cursor, conn)
    # setup default character
    client.visible_characters = load_all_characters_and_return_visible_ones(
        CONFIG.get("character_directories"), cursor
    )
    conn.commit()
    await client.tree.sync()
    asyncio.create_task(attend_chatbot_request(client))


@client.event
async def on_message(message):
    if message.author == client.user or (
        CONFIG.get("reply_to_other_bots", False) and message.author.bot
    ):  # don't reply to self, don't reply to bots if don't reply to bots
        return False
    else:
        text = message.clean_content
        ctx = await client.get_context(message)
        # conn, cursor = db.connect_to_db()
        try:
            # this one only registers if it doesn't exist
            db.check_and_register_channel_in_database(
                message.channel.id,
                message.guild.id if message.guild else None,
                cursor,
                ctx.message.channel.type == discord.ChannelType.private,
            )
            if client.user.mentioned_in(message) or (
                db.can_bot_speak_freely_in_current_room(message.channel.id, cursor)
            ):
                number_of_messages_for_author = (
                    check_number_of_messages_for_author_in_queue(message)
                )
                if number_of_messages_for_author > 10:
                    await message.channel.send(
                        f"{message.author.mention} {ctx.bot.user.display_name} is responding to at least ten of your requests, please allow {ctx.bot.user.display_name} to finish before requesting more messages.",
                    )
                else:
                    if f"@{client.user.display_name}" in text:
                        text = text.replace(f"@{client.user.display_name}", "")
                    request = queuing.ChatGenerationRequest(
                        message.channel.id,
                        message.author.id,
                        message.id,
                        message.author.display_name,
                        text,
                        False,
                    )
                    request_queue.put(request)
                # conn.close()
        except Exception as e:
            conn.rollback()
            logging.error(f"Rolling back, error in chatbot generation: {e}")


async def character_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    characters = interaction.client.visible_characters
    return [
        app_commands.Choice(name=char, value=char)
        for char in characters
        if current in char
    ]


@client.hybrid_command(description="Displays command information.")
@app_commands.describe()
async def help(ctx: discord.Interaction):
    await ctx.send(
        embed=discord.Embed().from_dict(
            {
                "title": f"Help Commands for {ctx.bot.user.display_name}!",
                "description": f"""• ``/helpinfo`` - Displays this help infobox\n• ``/channelinfo`` - Displays the current channel's active characters, user nicknames and whether the bot will reply to all messages.\n• ``/activate`` - Activates a character in the current channel, so that the character will respond if the chatbot is invoked.\n• ``/deactivate`` - Deactivates a character in the current channel, so they will not respond to messages.\n• ``/reset`` - Resets the chatbot's memory of the message history in the current channel, and optionally reset scenarios and deactivate characters.\n• ``/cont`` - Continues the generation, so active characters will speak for a given number of 'turns'. Maximum set in config.\n• ``/changemyname`` - Changes the name that the chatbot knows you as and characters will refer to you as, in the current channel.\n• ``/scenario`` - Sets a scene for the current channel, which the chatbot will take into account\n• ``/replyall`` - Toggles whether the character will reply to all messages or not in the current channel - bot owner command.\n• ``/hallucinate`` - Request a raw text generation without any character data using the message as a raw prompt.\n• ``/about`` - About this chatbot!\n• ``/refresh_characters`` - Reload the character files - bot owner command.\n""",
            }
        ),
        ephemeral=True,
    )


@client.hybrid_command(description="Generates text without any character")
@app_commands.describe()
async def hallucinate(ctx: discord.Interaction, message: str):
    logging.debug(f"Text generation request: {message}")
    try:
        message = message.replace("\\n", "\n")
        sent_message = await ctx.send(f"**{message}**")

        # request = queuing.GenericGenerationRequest(ctx.channel.id, ctx.message.author.id, message, False, sent_message)
        # request_queue.put(request)
        params = CONFIG.get("generate_params", {})
        params["auto_max_new_tokens"] = True

        response = await api.generate_text(message, params)
        logging.debug(f"Text generation: {response}")
        await sent_message.edit(content=f"{sent_message.content}{response}")
    except Exception as e:
        logging.error(f"Error in generation: {e}")


@client.hybrid_command(description="About the bot")
@app_commands.describe()
async def about(ctx: discord.Interaction):
    await ctx.send(
        embed=discord.Embed().from_dict(
            {
                "title": f"About",
                "description": f"""{ctx.bot.user.display_name} is a discord bot connected to a text generation AI program that has loaded a large language model. Type ``/helpinfo`` for help with commands.\n\nIt loads character prompts from files and uses those character prompts to roleplay as those characters, generating responses for entertainment purposes. The characters will remember the most recent conversations that it has had and will be able to carry on a conversation based on that history, but each channel that this bot is in will have a separate chat history (and keep in mind that the person hosting the chatbot may be able to see your conversations, even in private DMs).\n\nThis chatbot uses oobabooga's [text-generation-webui](https://github.com/oobabooga/text-generation-webui) as the backend to host the AI and assumes settings and models will be calibrated there.\n\nThis chatbot was written by Cadaeic, starting out as an edit to mercm8's fork of [chat-llama-discord-bot](https://github.com/mercm8/chat-llama-discord-bot), and is under the MIT license.""",
            },
        ),
        ephemeral=True,
    )


@client.hybrid_command(
    description=f"Continue generated conversation for at most {CONFIG.get('max_rounds_in_continuation', 5)} turn(s), default 1."
)
@app_commands.describe()
async def cont(
    ctx: discord.Interaction,
    number: Optional[int] = commands.parameter(
        default=1, description="Number of turns for characters to speak"
    ),
):
    number = 1 if number < 1 else number
    number = (
        CONFIG.get("max_rounds_in_continuation", 5)
        if number > CONFIG.get("max_rounds_in_continuation", 5)
        else number
    )
    # conn, cursor = db.connect_to_db()
    embed_message = (
        f"Continuing generation for {number} turns."
        if number > 1
        else "Continuing generation."
    )
    await ctx.send(
        embed=discord.Embed().from_dict({"title": embed_message, "description": ""})
    )
    try:
        for x in range(number):
            request = queuing.ChatGenerationRequest(
                ctx.message.channel.id,
                ctx.message.author.id,
                None,
                ctx.message.author.display_name,
                None,
                True,
            )
            request_queue.put(request)
            conn.commit()
        # conn.close()
    except Exception as e:
        conn.rollback()
        # conn.close()
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Failed to generate continuation.",
                    "description": f"Error: {e}",
                }
            )
        )
        logging.error(e)


@client.hybrid_command(
    description="Activate character for current room and optionally set/change scenario"
)
@app_commands.describe()
@app_commands.autocomplete(character=character_autocomplete)
async def activate(
    ctx: discord.Interaction,
    character: str = commands.parameter(description="The character to be activated"),
    say_greeting: Optional[bool] = commands.parameter(
        default=True,
        description="Whether the character should say their greeting, defaults to true",
    ),
    scenario: Optional[str] = commands.parameter(
        default=None,
        description="An optional character-specific context only this character will take into account",
    ),
    negative_prompt: Optional[str] = commands.parameter(
        default=None,
        description="An optional negative prompt the character's responses will try to avoid",
    ),
):
    if scenario:
        scenario = scenario.replace("\\n", "\n")
    if negative_prompt:
        negative_prompt = negative_prompt.replace("\\n", "\n")
    # conn, cursor = db.connect_to_db()
    db.check_and_register_channel_in_database(
        ctx.message.channel.id,
        ctx.message.guild.id if ctx.message.guild else None,
        cursor,
        ctx.message.channel.type == discord.ChannelType.private,
    )
    conn.commit()
    # check character exists
    character_check = db.retrieve_character_information_by_filename(character, cursor)
    if len(character_check) > 0:
        request = queuing.ActivateRequest(
            channel_id=ctx.channel.id,
            author_id=ctx.author.id,
            character_name=character,
            greeting=say_greeting,
            scenario=scenario,
            negative_prompt=negative_prompt,
        )
        request_queue.put(request)
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Queued request to activate character {character}.",
                    "description": "",
                }
            ),
            ephemeral=True,
        )
    else:
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Could not find {character}.",
                    "description": "",
                }
            ),
            ephemeral=True,
        )


@client.hybrid_command(description="Deactivate character for current room")
@app_commands.describe()
async def deactivate(
    ctx: discord.Interaction,
    character: str = commands.parameter(description="The character to be deactivated"),
):
    # conn, cursor = db.connect_to_db()

    request = queuing.GenericDatabaseRequest(
        channel_id=ctx.message.channel.id,
        author_id=ctx.message.author.id,
        database_func=db.set_active_character_per_room,
        func_kwargs={
            "character_filename": character,
            "channel_id": ctx.message.channel.id,
            "is_active": False,
            "scenario": None,
        },
        success_embed={
            "title": f"{character} now deactivated in this channel.",
            "description": f"Any character specific scenarios for {character} have been reset.",
        },
        failure_embed={
            "title": f"Failed to deactivate {character}.",
            "description": "Error: {{e}}",
        },
    )
    request_queue.put(request)
    await ctx.send(
        embed=discord.Embed().from_dict(
            {
                "title": f"Queued request to deactivate character.",
                "description": "",
            }
        ),
        ephemeral=True,
    )


@client.hybrid_command(description="Sets a scene for the current channel")
@app_commands.describe()
async def scenario(
    ctx: discord.Interaction,
    scenario: Optional[str] = commands.parameter(
        description="The context all characters in this channel will take into account",
        default=None,
    ),
):
    if scenario:
        scenario = scenario.replace("\\n", "\n")
    db.check_and_register_channel_in_database(
        ctx.message.channel.id,
        ctx.message.guild.id if ctx.message.guild else None,
        cursor,
        ctx.message.channel.type == discord.ChannelType.private,
    )
    success_embed_title = (
        f"Added scenario to current room for the chatbot to take into account."
        if scenario
        else "Removed scenario from current room."
    )

    request = queuing.GenericDatabaseRequest(
        channel_id=ctx.message.channel.id,
        author_id=ctx.message.author.id,
        database_func=db.add_scenario_to_current_room,
        func_kwargs={
            "channel_id": ctx.message.channel.id,
            "scenario": scenario or None,
        },
        success_embed={
            "title": success_embed_title,
            "description": f"{scenario if scenario else ''}",
        },
        failure_embed={
            "title": f"Failed to change scenario.",
            "description": "Error: {{e}}",
        },
    )
    request_queue.put(request)
    await ctx.send(
        embed=discord.Embed().from_dict(
            {
                "title": f"Queued request to set scenario for current room.",
                "description": "",
            }
        ),
        ephemeral=True,
    )


@client.hybrid_command(
    description="Set whether the chatbot will reply to every message in this channel, bot owner command"
)
@app_commands.describe()
async def replyall(
    ctx: discord.Interaction,
    replyall: bool = commands.parameter(
        description="Whether the chatbot will reply to all messages in this channel"
    ),
):
    # conn, cursor = db.connect_to_db()
    # if ctx.bot.is_owner(ctx.message.author.id):
    try:
        db.register_or_update_channel_in_database(
            ctx.message.channel.id, ctx.guild.id, replyall, cursor
        )
        conn.commit()
        embed_title = (
            f"{ctx.bot.user.display_name} will reply to all messages in this channel."
            if replyall
            else f"{ctx.bot.user.display_name} will not reply to all messages in this channel."
        )
        # conn.close()
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": embed_title,
                    "description": "",
                }
            )
        )
    except Exception as e:
        conn.rollback()
        # conn.close()
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Failed to set replying behaviour in this channel.",
                    "description": f"Error: {e}",
                }
            )
        )
        logging.error(e)
    # else:
    #     await ctx.send(
    #         embed=discord.Embed().from_dict(
    #             {
    #                 "title": f"Sorry, only {ctx.bot.user.display_name}'s owner can use this command.",
    #                 "description": "",
    #             }
    #         ),
    #         ephemeral=True,
    #     )


@client.hybrid_command(
    description="Changes the name that the bot knows you as, defaults to your discord username"
)
async def changemyname(
    ctx: discord.Interaction,
    name: Optional[str] = commands.parameter(
        description="The name the characters will know and address you as, none for reset",
        default=None,
    ),
):
    if name:
        user_name = name
        success_embed_title = f"Set chatbot nickname for {ctx.message.author.display_name} to {user_name}."

    else:
        user_name = ctx.message.author.display_name
        success_embed_title = f"Reset chatbot nickname for {user_name}."

    # conn, cursor = db.connect_to_db()
    db.register_or_update_user_in_database(
        ctx.message.author.id, ctx.message.author.display_name, cursor
    )
    conn.commit()
    request = queuing.GenericDatabaseRequest(
        channel_id=ctx.channel.id,
        author_id=ctx.message.author.id,
        database_func=db.add_or_update_user_nickname,
        func_kwargs={
            "discord_id": ctx.message.author.id,
            "channel_id": ctx.channel.id,
            "nickname": user_name,
        },
        success_embed={
            "title": success_embed_title,
            "description": "",
        },
        failure_embed={
            "title": f"Failed to set chatbot nickname for {ctx.message.author.display_name} to {user_name}.",
            "description": "Error: {{e}}",
        },
    )
    request_queue.put(request)
    await ctx.send(
        embed=discord.Embed().from_dict(
            {
                "title": f"Queued request to change {ctx.message.author.display_name} to {user_name}.",
                "description": f"",
            }
        ),
        ephemeral=True,
    )


@client.hybrid_command(
    description="For this channel, reset chat history, and optionally scenarios/characters"
)
async def reset(
    ctx: discord.Interaction,
    clear_all_scenarios: Optional[bool] = commands.parameter(
        description="Whether to clear both channel and character scenarios",
        default=False,
    ),
    deactivate_all_characters: Optional[bool] = commands.parameter(
        description="Whether to deactivate all characters in current channel",
        default=False,
    ),
    resend_greetings: Optional[bool] = commands.parameter(
        description="Whether to resend greetings from active characters",
        default=False,
    ),
):
    # conn, cursor = db.connect_to_db()
    success_embed_description = ""
    if clear_all_scenarios:
        success_embed_description += (
            "Clearing both channel scenario and character scenarios. "
        )
    if deactivate_all_characters:
        success_embed_description += "Deactivating all characters in current channel."
    request = queuing.ClearRequest(
        channel_id=ctx.channel.id,
        author_id=ctx.message.author.id,
        clear_history=True,
        clear_activated_characters=deactivate_all_characters,
        clear_channel_scenario=clear_all_scenarios,
        clear_character_scenarios=clear_all_scenarios,
    )
    request_queue.put(request)
    if resend_greetings and not deactivate_all_characters:
        chardata = db.get_active_character_data_per_room(ctx.channel.id, cursor)
        for character in chardata:
            if character["greeting"]:
                request = queuing.SaveAndSendMessageRequest(
                    ctx.channel.id,
                    ctx.message.author.id,
                    character["name"],
                    character["greeting"],
                    display_author=True,
                )
                request_queue.put(request)
        success_embed_description += "Active characters will resend greetings."

    await ctx.send(
        embed=discord.Embed().from_dict(
            {
                "title": f"Queued request to reset chat history.",
                "description": success_embed_description,
            }
        ),
        ephemeral=True,
    )


@client.hybrid_command(description="Reload the character files, bot owner command")
async def reload_characters(ctx: discord.Interaction):
    if ctx.bot.is_owner(ctx.message.author.id):
        try:
            refresh_characters(ctx, cursor)
            conn.commit()
            # conn.close()
            await ctx.send(
                embed=discord.Embed().from_dict(
                    {
                        "title": f"Refreshed characters and reloaded from file.",
                        "description": "",
                    }
                ),
                ephemeral=True,
            )
        except Exception as e:
            conn.rollback()
            # conn.close()
            await ctx.send(
                embed=discord.Embed().from_dict(
                    {
                        "title": f"Failed to reload for some reason.",
                        "description": f"Error: {e}",
                    }
                ),
                ephemeral=True,
            )
            logging.error(e)
    else:
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Sorry, only {ctx.bot.user.display_name}'s owner can use this command.",
                    "description": "",
                }
            ),
            ephemeral=True,
        )


@client.hybrid_command(description="Chatbot info for current channel")
async def channelinfo(ctx: discord.Interaction):
    # conn, cursor = db.connect_to_db()
    try:
        db.check_and_register_channel_in_database(
            ctx.message.channel.id,
            ctx.message.guild.id if ctx.message.guild else None,
            cursor,
            ctx.message.channel.type == discord.ChannelType.private,
        )
        chardata = db.get_active_character_data_per_room(ctx.message.channel.id, cursor)
        if len(chardata) > 0:
            charstring = "The current character(s) are active in this channel:\n"
            for c in chardata:
                charstring = charstring + f"• **{c['filename']}**"
                if c["scenario"]:
                    charstring = (
                        charstring
                        + f"\n\t{c['filename']}'s Scenario: {c['scenario']}\n"
                    )
                charstring = charstring + "\n"
        else:
            charstring = "There are no characters active in this channel.\n"

        namedata = db.get_nicknames_per_room(ctx.message.channel.id, cursor)
        if len(namedata) > 0:
            namestring = "\nIn this channel, this chatbot knows the following users as the following nicknames:\n"
            for n in namedata:
                namestring += f"• {n['display_name']} as **{n['nickname']}**\n"
        else:
            namestring = ""

        roomdata = db.can_bot_speak_freely_in_current_room(
            ctx.message.channel.id, cursor
        )
        roomstring = (
            f"\n{ctx.bot.user.display_name} will reply to all messages in current channel\n"
            if roomdata
            else f"\n{ctx.bot.user.display_name} will only respond to messages with **@{ctx.bot.user.display_name}** and to messages replying to the bot's messages\n"
        )

        scenario = db.get_scenario_from_current_room(ctx.message.channel.id, cursor)
        scenariostring = (
            f'\nThe current scenario is "{scenario}"'
            if scenario
            else "\nThere is no current scenario for this channel"
        )

        conn.commit()
        # conn.close()
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Chatbot info for the current channel",
                    "description": f"{charstring}{namestring}{roomstring}{scenariostring}",
                }
            ),
            ephemeral=True,
        )
    except Exception as e:
        conn.rollback()
        # conn.close()
        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": f"Failed to get info for current channel.",
                    "description": f"Error: {e}",
                }
            )
        )
        logging.error(e)


@client.hybrid_command(
    description="Sets the generation parameters for response generation, no validation yet lol"
)
async def generationparams(
    ctx: discord.Interaction,
    max_new_tokens: Optional[int] = None,
    auto_max_new_tokens: Optional[bool] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    typical_p: Optional[float] = None,
    epsilon_cutoff: Optional[float] = None,
    eta_cutoff: Optional[float] = None,
    tfs: Optional[float] = None,
    top_a: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
    repetition_penalty_range: Optional[int] = None,
    top_k: Optional[int] = None,
    no_repeat_ngram_size: Optional[int] = None,
    num_beams: Optional[int] = None,
    penalty_alpha: Optional[float] = None,
    length_penalty: Optional[float] = None,
    early_stopping: Optional[bool] = None,
    mirostat_mode: Optional[int] = None,
    mirostat_tau: Optional[float] = None,
    mirostat_eta: Optional[float] = None,
    guidance_scale: Optional[float] = None,
    negative_prompt: Optional[str] = None,
    stopping_strings: Optional[str] = None,
    reset_all: Optional[bool] = False,
):
    args = locals()
    params = {}

    if "reset_all" in args and args["reset_all"]:
        TOKEN, CONFIG = loading.load_config("config.yaml")
        success_embed_title = "Reset generation params."
        success_embed_message = ""
    else:
        success_embed_message = ""
        for k in args:
            if k == "ctx":
                continue
            if k == "stopping_strings" and args[k]:
                params[k] = args[k].split(",")
                success_embed_message += f"\n• {k} to {args[k]}"
            if args[k]:
                params[k] = args[k]
                success_embed_message += f"\n• {k} to {args[k]}"
        # TODO: validation of values

        if params != {}:
            success_embed_title = "Set following generation params:"
            update_generation_params(params)
        else:
            success_embed_title = "No parameters seem to have been set."

        await ctx.send(
            embed=discord.Embed().from_dict(
                {
                    "title": success_embed_title,
                    "description": success_embed_message,
                }
            ),
        )


client.run(TOKEN, root_logger=True, log_handler=handler)

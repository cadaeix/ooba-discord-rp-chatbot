from __future__ import annotations
from typing import Optional
from pathlib import Path
import sqlite3
import os, yaml, json
from . import api


def connect_to_db():  # standardise db connection name
    conn = sqlite3.connect("bot.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    return conn, cursor


def setup_database(cursor: any, conn: any):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS room
                        (room_id INTEGER PRIMARY KEY, channel_id INTEGER, server_id INTEGER, scenario TEXT, free_to_speak INTEGER)"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS characters
                        (character_id INTEGER PRIMARY KEY, filename TEXT UNIQUE, name TEXT, persona TEXT, example_conversation TEXT, greeting TEXT)"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS users
                        (user_id INTEGER PRIMARY KEY, discord_id INTEGER UNIQUE, username TEXT)"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS active_characters
                        (active_characters_id INTEGER PRIMARY KEY, active_room INTEGER, character INTEGER, active INTEGER, scenario TEXT, negative_prompt TEXT,
                       FOREIGN KEY(active_room) REFERENCES room(room_id), FOREIGN KEY(character) REFERENCES characters(character_id))"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS users_nickname
                        (users_nickname_id INTEGER PRIMARY KEY, active_room INTEGER, user INTEGER, nickname TEXT,
                       FOREIGN KEY(active_room) REFERENCES room(room_id), FOREIGN KEY(user) REFERENCES users(user_id))"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS messages
                        (message_id INTEGER PRIMARY KEY, discord_id INTEGER, channel int, author TEXT, message_content TEXT, token_count INTEGER, archived INTEGER,
                       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                       FOREIGN KEY(channel) REFERENCES room(room_id))"""
    )
    conn.commit()


def drop_everything(cursor: any):
    cursor.execute("""DROP TABLE messages""")
    cursor.execute("""DROP TABLE users_nickname""")
    cursor.execute("""DROP TABLE active_characters""")
    cursor.execute("""DROP TABLE users""")
    cursor.execute("""DROP TABLE characters""")
    cursor.execute("""DROP TABLE room""")


def rollback(conn: any):
    conn.rollback()


def check_existence_of_unique_record(
    table: str, id_column: str, checked_column: str, checked_value: str, cursor: any
):
    if not id_column:
        id_column = f"{table}_id"
    cursor.execute(
        f"""SELECT {id_column} FROM {table} WHERE {checked_column}=?""",
        (checked_value,),
    )
    result = cursor.fetchone()
    return result[0] if result else None


def check_existence_of_unique_record_with_two_fields(
    table: str,
    checked_column1: str,
    checked_value1: any,
    checked_column2: str,
    checked_value2: any,
    cursor: any,
    id_column: Optional[str] = None,
):
    if not id_column:
        id_column = f"{table}_id"
    cursor.execute(
        f"""SELECT {id_column} FROM {table} WHERE {checked_column1}=? AND {checked_column2}=?""",
        (checked_value1, checked_value2),
    )
    result = cursor.fetchone()
    return result[0] if result else None


def register_or_update_character_in_database(
    character_name: str,
    character_filename: str,
    character_context: str,
    cursor: any,
    character_example_conversation: Optional[str] = None,
    character_greeting: Optional[str] = None,
):
    character_id_if_exists = check_existence_of_unique_record(
        "characters", "character_id", "filename", character_filename, cursor
    )
    if character_id_if_exists:
        cursor.execute(
            """INSERT OR REPLACE INTO characters
                               (character_id, name, filename, persona, example_conversation, greeting)
                               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                character_id_if_exists,
                character_name,
                character_filename,
                character_context,
                character_example_conversation,
                character_greeting,
            ),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO characters
                               (name, filename, persona, example_conversation, greeting)
                               VALUES (?, ?, ?, ?, ?)""",
            (
                character_name,
                character_filename,
                character_context,
                character_example_conversation,
                character_greeting,
            ),
        )
    return cursor.rowcount > 0  # true if successful


def retrieve_character_information_by_name(character_name: str, cursor: any):
    cursor.execute("""SELECT * FROM characters WHERE name=?""", (character_name,))
    rows = cursor.fetchall()
    return rows


def retrieve_character_information_by_filename(filename: str, cursor: any):
    cursor.execute("""SELECT * FROM characters WHERE filename=?""", (filename,))
    rows = cursor.fetchall()
    return rows


def check_and_register_channel_in_database(
    channel_id: int, server_id: int, cursor: any, free_to_speak: bool = False
):
    room_id_if_exists = check_existence_of_unique_record(
        "room", "room_id", "channel_id", channel_id, cursor
    )
    if not room_id_if_exists:
        cursor.execute(
            """INSERT OR REPLACE INTO room
                              (channel_id, server_id, free_to_speak)
                              VALUES (?, ?, ?)""",
            (channel_id, server_id, int(free_to_speak)),
        )
    return cursor.rowcount > 0  # true if successful)


def register_or_update_channel_in_database(
    channel_id: int, server_id: int, free_to_speak: bool, cursor: any
):
    room_id_if_exists = check_existence_of_unique_record(
        "room", "room_id", "channel_id", channel_id, cursor
    )
    if room_id_if_exists:
        cursor.execute(
            """INSERT OR REPLACE INTO room
                              (room_id, channel_id, server_id, free_to_speak)
                              VALUES (?, ?, ?, ?)""",
            (room_id_if_exists, channel_id, server_id, int(free_to_speak)),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO room
                              (channel_id, server_id, free_to_speak)
                              VALUES (?, ?, ?)""",
            (channel_id, server_id, int(free_to_speak)),
        )
    return cursor.rowcount > 0  # true if successful


def toggle_channel_speakiness_and_return_speakiness(
    channel_id: int, server_id: int, cursor: any
):
    cursor.execute(
        """SELECT free_to_speak, room_id FROM room WHERE channel_id = ?""",
        (channel_id,),
    )

    result = cursor.fetchone()
    speakiness = result["free_to_speak"] if result else None
    if speakiness:
        cursor.execute(
            """INSERT OR REPLACE INTO room
                        (room_id, channel_id, server_id, free_to_speak)
                        VALUES (?, ?, ?, ?)""",
            (result["room_id"], channel_id, server_id, int(speakiness == 0)),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO room
                        (channel_id, server_id, free_to_speak)
                        VALUES (?, ?, ?)""",
            (channel_id, server_id, 1),
        )
    return speakiness != 1


def register_or_update_user_in_database(discord_id: int, username: int, cursor: any):
    user_id_if_exists = check_existence_of_unique_record(
        "users", "user_id", "discord_id", discord_id, cursor
    )
    if user_id_if_exists:
        cursor.execute(
            """INSERT OR REPLACE INTO users
                              (user_id, discord_id, username)
                               VALUES (?, ?, ?)""",
            (user_id_if_exists, discord_id, username),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO users
                              (discord_id, username)
                              VALUES (?, ?)""",
            (discord_id, username),
        )
    return cursor.rowcount > 0  # true if successful


def add_or_update_user_nickname(
    discord_id: int, channel_id: int, nickname: str, cursor: any
):
    cursor.execute("""SELECT user_id FROM users WHERE discord_id=?""", (discord_id,))
    user_id = cursor.fetchone()[0]
    cursor.execute("""SELECT room_id FROM room WHERE channel_id=?""", (channel_id,))
    room_id = cursor.fetchone()[0]
    table_id_if_exists = check_existence_of_unique_record_with_two_fields(
        "users_nickname", "active_room", room_id, "user", user_id, cursor
    )
    if table_id_if_exists:
        cursor.execute(
            """INSERT OR REPLACE INTO users_nickname
                              (users_nickname_id, active_room, user, nickname)
                              VALUES (?, ?, ?, ?)""",
            (table_id_if_exists, room_id, user_id, nickname),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO users_nickname
                              (active_room, user, nickname)
                              VALUES (?, ?, ?)""",
            (room_id, user_id, nickname),
        )
    return cursor.rowcount > 0  # true if successful


def lookup_nickname(discord_id: int, channel_id: int, cursor: any):
    cursor.execute(
        """SELECT nickname
                      FROM users_nickname
                      INNER JOIN users ON users_nickname.user = users.user_id
                      INNER JOIN room ON room.room_id = users_nickname.active_room
                      WHERE users.discord_id = ? AND room.channel_id = ?""",
        (discord_id, channel_id),
    )
    nickname = cursor.fetchone()
    if nickname:
        return nickname[0]
    else:
        cursor.execute(
            """SELECT username FROM users WHERE discord_id = ?""", (discord_id,)
        )
        return cursor.fetchone()[0]


def set_active_character_per_room(
    character_filename: str,
    channel_id: int,
    cursor: any,
    is_active: bool = True,
    scenario: Optional[str] = None,
    negative_prompt: Optional[str] = None,
):
    cursor.execute(
        """SELECT character_id FROM characters WHERE filename=?""",
        (character_filename,),
    )
    character = cursor.fetchone()
    if not character:
        raise Exception("Character not found.")
    char_id = character[0]
    cursor.execute("""SELECT room_id FROM room WHERE channel_id=?""", (channel_id,))
    room_id = cursor.fetchone()[0]
    table_id_if_exists = check_existence_of_unique_record_with_two_fields(
        "active_characters", "active_room", room_id, "character", char_id, cursor
    )
    if table_id_if_exists:
        cursor.execute(
            """INSERT OR REPLACE INTO active_characters
                              (active_characters_id, active_room, character, active, scenario, negative_prompt)
                              VALUES (?, ?, ?, ?, ?, ?)""",
            (
                table_id_if_exists,
                room_id,
                char_id,
                int(is_active),
                scenario,
                negative_prompt,
            ),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO active_characters
                              (active_room, character, active, scenario, negative_prompt)
                              VALUES (?, ?, ?, ?, ?)""",
            (room_id, char_id, int(is_active), scenario, negative_prompt),
        )
    return cursor.rowcount > 0  # true if successful


def toggle_character_activity_and_return_activity(
    character_filename: str, channel_id: int, cursor: any
):
    cursor.execute(
        """SELECT character_id FROM characters WHERE filename=?""",
        (character_filename,),
    )
    char_id = cursor.fetchone()[0]
    cursor.execute("""SELECT room_id FROM room WHERE channel_id=?""", (channel_id,))
    room_id = cursor.fetchone()[0]
    cursor.execute(
        """SELECT active_characters_id, active FROM active_characters WHERE character = ? AND active_room = ?""",
        (char_id, room_id),
    )
    result = cursor.fetchone()
    activity = result["active"] if result else None
    if activity == None:
        cursor.execute(
            """INSERT OR REPLACE INTO active_characters
                                (active_room, character, active)
                                VALUES (?, ?, ?)""",
            (room_id, char_id, 1),
        )
    else:
        cursor.execute(
            """INSERT OR REPLACE INTO active_characters
                (active_characters_id, active_room, character, active)
                VALUES (?, ?, ?, ?)""",
            (result["active_characters_id"], room_id, char_id, int(activity == 0)),
        )
    return activity != 1


def can_bot_speak_freely_in_current_room(channel_id: int, cursor: any):
    cursor.execute(
        """SELECT free_to_speak FROM room WHERE channel_id = ?""", (channel_id,)
    )
    return cursor.fetchone()[0] == 1


# assume that you run the register room command somewhere before this
def add_scenario_to_current_room(channel_id: int, scenario: Optional[str], cursor: any):
    cursor.execute(
        """UPDATE room SET scenario = ? WHERE channel_id = ?""", (scenario, channel_id)
    )
    return cursor.rowcount > 0


def get_scenario_from_current_room(channel_id: int, cursor: any):
    cursor.execute("""SELECT scenario FROM room WHERE channel_id = ?""", (channel_id,))
    scenario = cursor.fetchone()
    return scenario[0] if scenario else None


def get_nicknames_per_room(channel_id: int, cursor: any):
    cursor.execute(
        """SELECT nickname, users.username as display_name
                      FROM users_nickname
                      INNER JOIN users
                      ON users_nickname.user = users.user_id
                      INNER JOIN room ON room.room_id = users_nickname.active_room
                      WHERE room.channel_id = ?""",
        (channel_id,),
    )
    return cursor.fetchall()


def get_active_character_data_per_room(channel_id: int, cursor: any):
    cursor.execute(
        """SELECT characters.character_id as id, characters.name as name, filename, persona, example_conversation, greeting, active_characters.scenario as scenario, active_characters.negative_prompt as negative_prompt
                      FROM characters
                      INNER JOIN active_characters
                      ON active_characters.character = characters.character_id
                      INNER JOIN room ON room.room_id = active_characters.active_room
                      WHERE room.channel_id = ? AND active_characters.active = 1""",
        (channel_id,),
    )
    return cursor.fetchall()


def get_active_character_count_per_room(channel_id: int, cursor: any):
    cursor.execute(
        """SELECT count(*)
            FROM characters
            INNER JOIN active_characters
            ON active_characters.character = characters.character_id
            INNER JOIN room ON room.room_id = active_characters.active_room
            WHERE room.channel_id = ? AND active_characters.active = 1""",
        (channel_id,),
    )
    return cursor.fetchone()[0]


def deactivate_all(channel_id: int, cursor: any):
    cursor.execute(
        """
              UPDATE active_characters
              SET active = 0,
              scenario = ?,
              negative_prompt = ?
              FROM (SELECT room_id FROM room WHERE room.channel_id = ?) as current_room
              WHERE active_characters.active_room = current_room.room_id
              """,
        (
            None,
            None,
            channel_id,
        ),
    )
    return cursor.rowcount > 0


def reset_all_active_character_scenarios(channel_id: int, cursor: any):
    cursor.execute(
        """
              UPDATE active_characters
              SET scenario = ?
              FROM (SELECT room_id FROM room WHERE room.channel_id = ?) as current_room
              WHERE active_characters.active_room = current_room.room_id
              """,
        (
            None,
            channel_id,
        ),
    )
    return cursor.rowcount > 0


def save_message(
    message: str,
    author: str,
    channel_id: int,
    message_id: int,
    cursor: any,
    should_count_tokens: Optional[bool] = False,
):
    cursor.execute("""SELECT room_id FROM room WHERE channel_id=?""", (channel_id,))
    room_id = cursor.fetchone()[0]

    token_count = (
        api.count_tokens(f"{author}: {message}") if should_count_tokens else None
    )

    # TODO: put check for unique record here for message updating, don't feel like doing it now

    cursor.execute(
        """INSERT OR REPLACE INTO messages
                       (discord_id, channel, author, message_content, token_count, archived)
                       VALUES
                       (?, ?, ?, ?, ?, ?)""",
        (message_id, room_id, author, message, token_count, 0),
    )
    return cursor.rowcount > 0  # true if successful


def get_message_history_from_channel(channel_id: str, cursor: any):
    cursor.execute(
        """SELECT message_content, author, token_count
                      FROM messages
                      INNER JOIN room ON room.room_id = messages.channel
                      WHERE room.channel_id = ? and messages.archived = 0
                      ORDER BY messages.timestamp
                      ASC LIMIT 200""",
        (channel_id,),
    )
    return cursor.fetchall()


def reset_memory_for_current_channel(channel_id: str, cursor: any):
    cursor.execute(
        """
              UPDATE messages
              SET archived = 1
              FROM (SELECT room_id FROM room WHERE room.channel_id = ?) as current_room
              WHERE messages.channel = current_room.room_id
              """,
        (channel_id,),
    )
    return cursor.rowcount > 0


def get_message_history_with_channel_before_specific_message_id(
    message_id: int, cursor: any
):
    cursor.execute(
        """SELECT timestamp, channel FROM messages WHERE message_id = ?""",
        (message_id,),
    )
    timestamp = cursor.fetchone()["timestamp"]
    room_id = cursor.fetchone()["room"]

    cursor.execute(
        """SELECT message_content, room.channel_id as channel_id, author, token_count
                      FROM messages
                      INNER JOIN room ON room.room_id = messages.channel
                      WHERE
                      channel = ?
                      and messages.archived = 0
                      and messages.timestamp <= ?
                      ORDER BY messages.timestamp
                      DESC LIMIT 200""",
        (room_id, timestamp),
    )
    return cursor.fetchall()


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


def save_user_message_to_history(
    user_discord_id: str,
    channel_discord_id: str,
    message_discord_id: str,
    message_content: str,
    discord_username: str,
    cursor: any,
    conn: any,
):
    register_or_update_user_in_database(user_discord_id, discord_username, cursor)
    author_name = lookup_nickname(user_discord_id, channel_discord_id, cursor)
    save_message(
        message_content,
        author_name,
        channel_discord_id,
        message_discord_id,
        cursor,
        True,
    )
    conn.commit()

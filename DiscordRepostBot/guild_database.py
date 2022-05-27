"""guild_database 

This module contains the sql database connection and functions necessary to run the repost bot for each individual
guild.

Author: Scott Nealon
"""

import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import discord
import discord.ext.commands
import emoji as emoji_library

logger = logging.getLogger(__name__)

class ReadableRow(sqlite3.Row):

    def __repr__(self):
        return f"sqlite3.Row({ {key: value for key, value in zip(self.keys(), self)} })"


class GuildDatabase:

    newest_version = 15

    def __init__(self, guild: discord.Guild, bot: discord.ext.commands.Bot):
        self.guild = guild
        self.bot = bot
        self.path = (
            Path(os.path.dirname(os.path.realpath(__file__))).joinpath("databases").joinpath(f"{guild.id}.sqlite3")
        )
        self._create_connection()

    def _create_connection(self):
        """Creates a connection to guild SQLite3 database, populating as necessary"""
        is_new_database = not self.path.exists()
        if is_new_database:
            logger.info(f'Creating new database for guild "{self.guild}".')
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = ReadableRow
        if not self._is_valid_database(new=is_new_database):
            self._create_database(is_new_database)

    def _is_valid_database(self, new: bool) -> bool:
        """Returns TRUE if able to match version in table, otherwise returns FALSE"""
        try:
            correct_version = self.version == self.newest_version
        except sqlite3.OperationalError as error:
            correct_version = False
        except TypeError as error:
            correct_version = False
        if not correct_version and not new:
            logger.warning(f"Invalid database for {self.guild} ({self.path.name}). Creating new database.")
        return correct_version

    def _create_database(self, new: bool):
        """Creates a new guild SQLite3 database"""
        if not new:
            # Delete and recreate database
            self.connection.close()
            os.remove(self.path)
            self.connection = sqlite3.connect(self.path)
        # Run commands
        self._create_version_table()
        self._create_updated_table()
        self._create_active_table()
        self._create_emoji_table()
        self._create_member_table()
        self._create_blacklisted_member_table()
        self._create_blacklisted_channels_table()
        self._create_originals_table()
        self._create_reposts_table()
        self.connection.commit()

    ### ABSTRACT QUERIES ###

    @staticmethod
    def _conditional_from_arguments(**kwargs):
        if any(value is not None for value in kwargs.values()):
            return f"WHERE {', '.join([f'{key} = :{key}' for key, value in kwargs.items() if value is not None])}"
        else:
            return ""

    def _query_table(self, table: str, **kwargs):
        query = f"SELECT * FROM {table} {self._conditional_from_arguments(**kwargs)}"
        return self.connection.execute(query, kwargs).fetchall()

    def _add_to_table(self, table: str, **kwargs):
        query = f"INSERT INTO {table} ({', '.join([key for key in kwargs])}) VALUES ({', '.join([f':{key}' for key in kwargs])})"
        return self.connection.execute(query, kwargs).fetchall()

    def _update_table(self, table: str, **kwargs):
        query = f"UPDATE {table} SET {', '.join([f'{key} = :{key}' for key in kwargs])} {self._conditional_from_arguments(**kwargs)}"
        return self.connection.execute(query, kwargs).fetchall()

    def _remove_from_table(self, table: str, **kwargs):
        query = f"DELETE FROM {table} {self._conditional_from_arguments(**kwargs)}"
        return self.connection.execute(query, kwargs).fetchall()

    ### PROPERTIES ###

    # VERSION #

    _verion_args = ""

    def _create_version_table(self):
        self.connection.execute("CREATE TABLE version(version INT NOT NULL);")
        self.connection.execute(
            "INSERT INTO version (version) VALUES (:version);",
            {"version": self.newest_version},
        )

    @property
    def version(self) -> int:
        return self.connection.execute("SELECT * FROM version;").fetchone()[0]

    # UPDATED #

    def _create_updated_table(self):
        self.connection.execute("CREATE TABLE updates(oldestUpdate FLOAT NOT NULL, lastUpdate FLOAT NOT NULL);")
        self.connection.execute(
            "INSERT INTO updates (oldestUpdate, lastUpdate) VALUES (:now, :now);", {"now": time.time()}
        )

    @property
    def oldest_update(self) -> float:
        return self.connection.execute("SELECT oldestUpdate FROM updates;").fetchone()[0]

    @oldest_update.setter
    def oldest_update(self, oldest_update: float):
        self.connection.execute("UPDATE updates SET oldestUpdate = :oldestUpdate;", {"oldestUpdate": oldest_update})

    @property
    def last_updated(self) -> float:
        return self.connection.execute("SELECT lastUpdate FROM updates;").fetchone()[0]

    @property
    def last_updated_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.last_updated)

    @last_updated.setter
    def last_updated(self, last_updated: float):
        self.connection.execute("UPDATE updates SET lastUpdate = :lastUpdate", {"lastUpdate": last_updated})

    # SERVER ACTIVE STATUS

    def _create_active_table(self):
        self.connection.executescript(
            """
            CREATE TABLE active(active INT NOT NULL);
            INSERT INTO active (active) VALUES (1)
            """
        )

    @property
    def active(self) -> bool:
        return self.connection.execute("SELECT * FROM active;").fetchone()[0]

    @active.setter
    def set_active(self, active: bool):
        self.connection.execute("UPDATE active SET active = :active", {"active": active})

    # EMOJI #

    _emoji = None

    def _create_emoji_table(self):
        self.connection.executescript(
            """
            CREATE TABLE emoji(emoji VARCHAR NOT NULL);
            INSERT INTO emoji (emoji) VALUES ("recycle")
            """
        )

    @property
    def emoji_str(self) -> str:
        return self.connection.execute("SELECT * FROM emoji;").fetchone()[0]

    @emoji_str.setter
    def set_emoji_str(self, emoji_str: str):
        self.connection.execute("UPDATE emoji SET emoji = :emoji", {"emoji": emoji_str})

    @property
    def emoji(self) -> discord.Emoji:
        """Save self._emoji to not need to search on every query."""
        # Get emoji string from database
        emoji_str = self.emoji_str
        # Compare name of emoji to saved emoji
        if not (type(self._emoji) == discord.Emoji and self._emoji.name == emoji_str) or (
            type(self._emoji) == str
            and self._emoji == emoji_library.EMOJI_ALIAS_UNICODE_ENGLISH.get(f":{emoji_str}:", None)
        ):
            # If nothing matches, try to find matching discord or unicode emoji
            for emoji in self.bot.emojis:
                if emoji.name == emoji_str:
                    self._emoji = emoji
            else:
                try:
                    self._emoji = emoji_library.EMOJI_ALIAS_UNICODE_ENGLISH[f":{emoji_str}:"]
                except:
                    raise ValueError(f"{emoji_str} not found in bot's emojis or unicode.")
        return self._emoji

    # MEMBERS #

    def _create_member_table(self):
        self.connection.execute("CREATE TABLE members(memberID INT NOT NULL PRIMARY KEY);")

    def get_members(self) -> tuple[tuple[int]]:
        return self.connection.execute("SELECT * FROM members").fetchall()

    def is_member(self, member_id: int) -> bool:
        matching_members = self.connection.execute(
            "SELECT * FROM members WHERE memberID = :memberID", {"memberID": member_id}
        ).fetchone()
        return len(matching_members) > 0

    def add_member(self, member: discord.Member):
        self.connection.execute("INSERT INTO members (memberID) VALUES (:memberID);", {"memberID": member.id})

    def remove_member(self, member: discord.Member):
        self.connection.execute("DELETE FROM members WHERE memberID = :memberID;", {"memberID": member.id})

    # BLACKLISTED MEMEBERS #

    def _create_blacklisted_member_table(self):
        self.connection.execute(
            "CREATE TABLE blacklistedMembers(memberID INT NOT NULL PRIMARY KEY, FOREIGN KEY (memberID) REFERENCES members(memberID));"
        )

    def get_blacklisted_members(self, member_id: int = "ANY") -> tuple[tuple[int]]:
        return self.connection.execute(
            "SELECT * FROM blacklistedMembers WHERE memberID = :memberID", {"memberID": member_id}
        ).fetchall()

    def add_blacklisted_member(self, member: discord.Member):
        self.connection.execute(
            "INSERT INTO blacklistedMembers (memberID) VALUES (:memberID);", {"memberID": member.id}
        )

    def remove_blacklisted_member(self, member: discord.Member):
        self.connection.execute("DELETE FROM blacklistedMembers WHERE memberID = :memberID;", {"memberID": member.id})

    # BLACKLISTED CHANNELS #

    def _create_blacklisted_channels_table(self):
        self.connection.execute("CREATE TABLE blacklistedChannels(channelID INT NOT NULL PRIMARY KEY);")

    def get_blacklisted_channels(self, channel_id: int = "ANY") -> tuple[tuple[int]]:
        return self.connection.execute(
            "SELECT * FROM blacklistedChannels WHERE channelID = :channelID", {"channelID": channel_id}
        ).fetchall()

    def add_blacklisted_channel(self, channel: discord.ChannelType):
        self.connection.execute(
            "INSERT INTO blacklistedChannels (channelID) VALUES (:channelID);", {"channelID": channel.id}
        )

    def remove_blacklisted_channel(self, channel: discord.ChannelType):
        self.connection.execute(
            "DELETE FROM blacklistedChannels WHERE channelID = :channelID;", {"channelID": channel.id}
        )

    # ORIGINALS #

    def _create_originals_table(self):
        self.connection.execute(
            """
            CREATE TABLE originals(
                url VARCHAR NOT NULL PRIMARY KEY,
                messageID INT NOT NULL,
                channelID INT NOT NULL,
                memberID INT NOT NULL,
                timestamp FLOAT NOT NULL,
                FOREIGN KEY (memberID) REFERENCES members(id)
            );
            """
        )

    def get_originals(
        self,
        url: str = None,
        message_id: int = None,
        channel_id: int = None,
        member_id: int = None,
        timestamp: float = None,
    ):
        var_mapping = {
            "url": url,
            "messageID": message_id,
            "channelID": channel_id,
            "memberID": member_id,
            "timestamp": timestamp,
        }
        return self._query_table("originals", **var_mapping)

    def add_original(self, url: str, message: discord.Message):
        var_mapping = {
            "url": url,
            "messageID": message.id,
            "channelID": message.channel.id,
            "memberID": message.author.id,
            "timestamp": message.created_at.timestamp(),
        }
        self._add_to_table("originals", **var_mapping)

    def update_original(self, url: str, message: discord.Message):
        var_mapping = {
            "url": url,
            "messageID": message.id,
            "channelID": message.channel.id,
            "memberID": message.author.id,
            "timestamp": message.created_at.timestamp(),
        }
        self._update_table("originals", **var_mapping)

    def remove_originals(
        self,
        url: str = "ANY",
        message_id: int = "ANY",
        channel_id: int = "ANY",
        member_id: int = "ANY",
        timestamp: float = "ANY",
    ):
        var_mapping = {
            "url": url,
            "messageID": message_id,
            "channelID": channel_id,
            "memberID": member_id,
            "timestamp": timestamp,
        }
        self._remove_from_table("originals", **var_mapping)

    # REPOSTS #

    def _create_reposts_table(self):
        self.connection.executescript(
            """
            CREATE TABLE reposts(
                url VARCHAR NOT NULL,
                messageID INT NOT NULL,
                channelID INT NOT NULL,
                memberID INT NOT NULL,
                timestamp FLOAT NOT NULL,
                FOREIGN KEY (url) REFERENCES urls(url),
                FOREIGN KEY (memberID) REFERENCES members(id)
            );
            CREATE UNIQUE INDEX repost_index ON REPOSTS (url, messageID, channelID);
            """
        )

    def get_reposts(
        self,
        url: str = None,
        message_id: int = None,
        channel_id: int = None,
        member_id: int = None,
        timestamp: float = None,
    ):
        var_mapping = {
            "url": url,
            "messageID": message_id,
            "channelID": channel_id,
            "memberID": member_id,
            "timestamp": timestamp,
        }
        return self._query_table("reposts", **var_mapping)

    def add_repost(self, url: str, message: discord.Message):
        var_mapping = {
            "url": url,
            "messageID": message.id,
            "channelID": message.channel.id,
            "memberID": message.author.id,
            "timestamp": message.created_at.timestamp(),
        }
        self._add_to_table("reposts", **var_mapping)

    def remove_reposts(
        self,
        url: str = "ANY",
        message_id: int = "ANY",
        channel_id: int = "ANY",
        member_id: int = "ANY",
        timestamp: float = "ANY",
    ):
        var_mapping = {
            "url": url,
            "messageID": message_id,
            "channelID": channel_id,
            "memberID": member_id,
            "timestamp": timestamp,
        }
        self._remove_from_table("reposts", **var_mapping)

    def commit(self):
        self.connection.commit()

    def __del__(self):
        """Close connection on deletion"""
        self.connection.close()

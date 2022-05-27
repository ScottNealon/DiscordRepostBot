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
from typing import Union

import discord
import discord.ext.commands
import emoji as emoji_library

logger = logging.getLogger(__name__)

# Read commands
sql_queries_dir = Path(os.path.dirname(os.path.realpath(__file__))).joinpath("SQL")
sql_queries: dict[str, str] = {}
for file in sql_queries_dir.iterdir():
    if file.suffix == ".sql":
        with open(file, "r") as file_handle:
            sql_queries[file.stem] = file_handle.read()


class GuildDatabase:

    newest_version = 12

    def __init__(self, guild: discord.Guild, bot: discord.ext.commands.Bot):
        self.guild = guild
        self.bot = bot
        self.path = (
            Path(os.path.dirname(os.path.realpath(__file__))).joinpath("databases").joinpath(f"{guild.id}.sqlite3")
        )
        self._emoji = None
        self._create_connection()

    def _create_connection(self):
        """Creates a connection to guild SQLite3 database, populating as necessary"""
        is_new_database = not self.path.exists()
        if is_new_database:
            logger.info(f'Creating new database for guild "{self.guild}".')
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        if not self._is_valid_database(new=is_new_database):
            self._create_database()

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

    def _create_database(self):
        """Creates a new guild SQLite3 database"""
        # Delete and recreate database
        self.connection.close()
        os.remove(self.path)
        self.connection = sqlite3.connect(self.path)
        # Run commands
        now = time.time()
        for command in sql_queries["create_database"].split(";"):
            self.connection.execute(command, {"newest_version": self.newest_version, "now": now})

    ### PROPERTIES ###

    @property
    def version(self) -> int:
        return self.connection.execute(sql_queries["get_version"]).fetchone()[0]

    @property
    def last_updated(self) -> float:
        return self.connection.execute(sql_queries["get_last_updated"]).fetchone()['lastUpdate']

    @property
    def last_updated_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.last_updated)

    @last_updated.setter
    def last_updated(self, last_updated: float):
        self.connection.execute(sql_queries["set_last_updated"], {"lastUpdate": last_updated})

    @property
    def active(self) -> bool:
        return self.connection.execute(sql_queries["get_active"]).fetchone()[0]

    @active.setter
    def set_active(self, active: bool):
        self.connection.execute(sql_queries["set_active"], {"active": active})

    @property
    def blacklisted_channels(self):
        return self.connection.execute(sql_queries["get_blacklisted_channels"]).fetchall()

    def add_blacklisted_channel(self, blacklisted_channel: str):
        self.connection.execute(sql_queries["add_blacklisted_channel"], {"id": blacklisted_channel})

    def remove_blacklisted_channel(self, blacklisted_channel: str):
        self.connection.execute(sql_queries["remove_blacklisted_channel"], {"blacklisted_channel": blacklisted_channel})

    @property
    def members(self) -> tuple[int]:
        return tuple(member["id"] for member in self.connection.execute(sql_queries["get_members"]).fetchall())

    def add_member(self, member: discord.Member):
        self.connection.execute(sql_queries["add_member"], {"id": member.id})

    @property
    def urls(self):
        return self.connection.execute(sql_queries["get_urls"]).fetchall()

    def get_url(self, url: str) -> sqlite3.Row:
        return self.connection.execute(sql_queries["get_url"], {"url": url}).fetchone()

    def add_url(self, url: str, message: discord.Message):
        self.connection.execute(
            sql_queries["add_url"],
            {
                "url": url,
                "messageID": message.id,
                "channelID": message.channel.id,
                "memberID": message.author.id,
                "timestamp": message.created_at.timestamp(),
            },
        )

    def set_url(self, url: str, message: discord.Message):
        self.connection.execute(
            sql_queries["set_url"],
            {
                "url": url,
                "messageID": message.id,
                "channelID": message.channel.id,
                "memberID": message.author.id,
                "timestamp": message.created_at.timestamp(),
            },
        )

    def remove_url(self, url: str):
        self.connection.execute(sql_queries["remove_url"], {"url": url})

    @property
    def reposts(self):
        return self.connection.execute(sql_queries["reposts"]).fetchall()

    def add_repost(self, url: str, message: discord.Message):
        self.connection.execute(
            sql_queries["add_repost"],
            {"messageID": message.id, "channelID": message.channel.id, "memberID": message.author.id, "url": url},
        )

    def remove_repost(self, url: str, message: discord.Message):
        self.connection.execute(sql_queries["remove_repost"], {"messageID": message.id, "url": url})

    @property
    def emoji_str(self) -> str:
        return self.connection.execute(sql_queries["get_emoji"]).fetchone()[0]

    @emoji_str.setter
    def set_emoji_str(self, emoji_str: str):
        self.connection.execute(sql_queries["set_emoji"], {"emoji": emoji_str})

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

    def commit(self):
        self.connection.commit()

    def __del__(self):
        """Close connection on deletion"""
        self.connection.close()

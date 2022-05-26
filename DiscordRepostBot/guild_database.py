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
from enum import Enum
from pathlib import Path

import discord
from discord.ext.commands import Bot

logger = logging.getLogger(__name__)

databases: dict[int, sqlite3.Connection] = {}
databases_dir_path = Path(os.path.dirname(os.path.realpath(__file__))).joinpath("databases")
current_database_version = 1

# Read commands for creating a new database
with open(Path(os.path.dirname(os.path.realpath(__file__))).joinpath("new_database.sql"), "r") as file_handle:
    new_database_sql_commands = file_handle.read()


def create_database_connection(guild: discord.Guild):
    """Creates a database connection to guild, populating as necessary"""
    database_path = databases_dir_path.joinpath(f"{guild.id}.sqlite3")
    is_new_database = not database_path.exists()
    if is_new_database:
        logger.info(f'Creating new database for guild "{guild}".')
    databases[guild.id] = sqlite3.connect(database_path)
    if not is_valid_database(guild, new=is_new_database):
        create_database(guild)


def create_database(guild: discord.Guild):
    """Creates a new guild database"""
    # Delete and recreate database
    databases[guild.id].close()
    database_path = databases_dir_path.joinpath(f"{guild.id}.sqlite3")
    os.remove(database_path)
    databases[guild.id] = sqlite3.connect(database_path)
    # Replace commands
    now = time.time()
    # updated_database_sql_commands = new_database_sql_commands.format_map(
    #     {"current_database_version": current_database_version, " now ": now}
    # )
    # Run commands
    for command in new_database_sql_commands.split(";"):
        databases[guild.id].execute(command, {"current_database_version": current_database_version, "now": now})
    # Commit
    databases[guild.id].commit()


def is_valid_database(guild: discord.Guild, new: bool):
    try:
        correct_version = get_version(guild) == current_database_version
    except sqlite3.OperationalError as error:
        correct_version = False
    except TypeError as error:
        correct_version = False
    if not correct_version:
        logger.warning(f'Invalid database for guild "{guild}". Creating new database.')
    return correct_version


def get_prefix_wrapper(bot: Bot, message: discord.Message) -> str:
    """Determines which prefix to use based on server preferences"""
    return get_prefix(message.guild)


async def review_messages(guild: discord.Guild, bot: discord.Client):
    """Reviews all messages in guild since last update"""
    logger.info(f"Updating channels in {guild}.")
    last_updated = datetime.fromtimestamp(get_last_updated(guild))
    blacklisted_channels = get_blacklisted_channels(guild)
    # Iterate across all text channels in guild
    for channel in guild.channels:

        # Skip non-text channels
        if not isinstance(channel, discord.TextChannel):
            logger.info(f"{guild}/#{channel} is not a text channel.")
            continue

        # Skip blacklisted channels
        if channel.id in blacklisted_channels:
            logger.warning(f"{guild}/#{channel} is blacklisted.")
            continue

        logger.info(f"{guild}/#{channel}")

        # Iterate across all messages in channel since last updated
        try:
            async for message in channel.history(after=last_updated, limit=None, oldest_first=True):
                review_message(message, bot)

        # Catch error incase unable to access channel
        except discord.Forbidden:
            logger.warning(f"{guild}/#{channel} cannot be accessed.")


class URL_STATUS(Enum):
    NEW = 0
    REPOST = 1
    REVERSE_REPOST = 2


def review_message(message: discord.Message, bot: discord.Client):
    """Reviews individual message to check for repost"""

    # Skip any message from self, bot, or starting with recognized command
    if (
        message.author == bot.user
        or message.author.bot
        or message.content.lower().startswith(get_prefix(message.guild))
    ):
        return

    # Search through every embed for a URL
    for embed in message.embeds:
        if embed.url == discord.Embed.Empty:
            continue

        url_status = check_if_repost(embed.url, message)

        log_message = f"{message.guild}/#{message.channel} at {message.created_at} by {message.author}: {embed.url}"
        if url_status == URL_STATUS.NEW:
            logger.debug(f"New URL found: {log_message}")
            add_new_url(message)
        elif url_status == URL_STATUS.REPOST:
            logger.debug(f"Repost found: {log_message}")
            mark_repost(message)
        elif url_status == URL_STATUS.REVERSE_REPOST:
            logger.debug(f"Reverse repose found: {log_message}")
            handle_reverse_repost(message)
        else:
            raise ValueError("Invalid URL status returned.")


def check_if_repost(url: str, message: discord.Message) -> int:
    """Returns whether URL is a repose or not"""
    # Check if URL has been posted before
    _, query_timestamp = check_url(url, message.guild)
    if query_timestamp is not None:
        if query_timestamp < message.created_at.timestamp():
            return URL_STATUS.REPOST
        else:
            return URL_STATUS.REVERSE_REPOST
    else:
        return URL_STATUS.NEW


def mark_repost(message: discord.Message):
    pass


def handle_reverse_repost(message: discord.Message):
    pass


def add_new_url(message: discord.Message):
    pass


def get_prefix(guild: discord.Guild) -> str:
    return databases[guild.id].execute("SELECT prefix FROM prefix").fetchone()[0]


def get_version(guild: discord.Guild) -> int:
    return databases[guild.id].execute("SELECT version FROM version").fetchone()[0]


def get_last_updated(guild: discord.Guild) -> float:
    return databases[guild.id].execute("SELECT lastUpdate FROM updates").fetchone()[0]


def get_active(guild: discord.Guild) -> bool:
    return bool(databases[guild.id].execute("SELECT active FROM active").fetchone()[0])


def get_blacklisted_channels(guild: discord.Guild) -> tuple[str]:
    return databases[guild.id].execute("SELECT channelID FROM blacklistedChannels").fetchall()


def check_url(url: str, guild: discord.Guild) -> tuple[int, float]:
    url_data = databases[guild.id].execute(f'SELECT messageID, timestamp FROM urls WHERE url = "{url}"').fetchone()
    if url_data == None:
        url_data = (None, None)
    return url_data

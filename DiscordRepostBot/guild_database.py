"""guild_database 

This module contains the sql database connection and functions necessary to run the repost bot for each individual
guild.

Author: Scott Nealon
"""

import logging
import os
import sqlite3
import time
from pathlib import Path

import discord
from discord.ext.commands import Bot

logger = logging.getLogger(__name__)

databases: dict[int, sqlite3.Connection] = {}
databases_dir_path = Path(os.path.dirname(os.path.realpath(__file__))).joinpath("databases")
current_database_version = "0.0"

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
    if not is_valid_database(guild, new=True):
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
    new_database_sql_commands
    updated_database_sql_commands = new_database_sql_commands.format_map(
        {"current_database_version": current_database_version, " now ": now}
    )
    # Run commands
    for command in updated_database_sql_commands.split(";"):
        databases[guild.id].execute(command)
    # Commit
    databases[guild.id].commit()


def is_valid_database(guild: discord.Guild, new: bool):
    try:
        return get_version(guild) == current_database_version
    except sqlite3.OperationalError as error:
        if not new:
            logger.warning(f'Invalid database for guild "{guild}". Creating new database.')
        return False
    except TypeError as error:
        if not new:
            logger.warning(f'Invalid database for guild "{guild}". Creating new database.')
        return False


def get_prefix_wrapper(bot: Bot, message: discord.Message) -> str:
    """Determines which prefix to use based on server preferences"""
    return get_prefix(message.guild)


def review_messages(guild: discord.Guild):
    """Reviews all messages in guild since last update"""
    now = time.time()
    last_updated = get_last_updated(guild)
    pass



def get_prefix(guild: discord.Guild) -> str:
    return databases[guild.id].execute("SELECT prefix FROM prefix").fetchone()[0]


def get_version(guild: discord.Guild) -> str:
    return databases[guild.id].execute("SELECT version FROM version").fetchone()[0]


def get_last_updated(guild: discord.Guild) -> float:
    return databases[guild.id].execute("SELECT lastUpdate FROM updates").fetchone()[0]


def get_active(guild: discord.Guild) -> bool:
    return bool(databases[guild.id].execute("SELECT active FROM active").fetchone()[0])

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


def create_database_connection(guild: discord.Guild):
    """Creates a database connection to guild, populating as necessary"""
    database_path = databases_dir_path.joinpath(f"{guild.id}.sqlite3")
    is_new_database = not database_path.exists()
    if is_new_database:
        logger.info(f'Creating new database for guild "{guild}".')
    databases[guild.id] = sqlite3.connect(database_path)
    if not is_valid_database(guild):
        if not is_new_database:
            logger.info(f'Invalid database for guild "{guild}". Creating new database.')
        create_database(guild)


def create_database(guild: discord.Guild):
    """Creates a new guild database"""
    # Delete and recreate database
    databases[guild.id].close()
    database_path = databases_dir_path.joinpath(f"{guild.id}.sqlite3")
    os.remove(database_path)
    databases[guild.id] = sqlite3.connect(database_path)
    # Populate database
    databases[guild.id].execute(
        """
        CREATE TABLE version(
            version VARCHAR NOT NULL
        );
        """
    )
    databases[guild.id].execute(
        f"""
        INSERT INTO version
            (version)
        VALUES
            ("{current_database_version}");
        """
    )
    databases[guild.id].execute(
        """
        CREATE TABLE updates(
            oldestUpdate FLOAT NOT NULL,
            newestUpdate FLOAT NOT NULL
        );
        """
    )
    now = time.time()
    databases[guild.id].execute(
        f"""
        INSERT INTO updates
            (oldestUpdate, lastUpdate)
        VALUES
            ({now}, {now});
        """
    )
    databases[guild.id].execute(
        """
        CREATE TABLE prefix(
            prefix VARCHAR NOT NULL
        );
        """
    )
    databases[guild.id].execute(
        f"""
        INSERT INTO prefix
            (prefix)
        VALUES
            ("$repost");
        """
    )
    databases[guild.id].execute(
        """
        CREATE TABLE active(
            active INT NOT NULL
        );
        """
    )
    databases[guild.id].execute(
        f"""
        INSERT INTO active
            (active)
        VALUES
            (1);
        """
    )
    # Commit
    databases[guild.id].commit()


def is_valid_database(guild: discord.Guild):
    try:
        database_version = (
            databases[guild.id].execute('SELECT version FROM version').fetchone()
        )[0]
        return database_version == current_database_version
    except sqlite3.OperationalError as error:
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
    return databases[guild.id].execute("SELECT prefix from prefix").fetchone()[0]

def get_last_updated(guild: discord.Guild) -> float:
    return databases[guild.id].execute("SELECT lastUpdate from updates").fetchone()[0]

def get_active(guild: discord.Guild) -> bool:
    return bool(databases[guild.id].execute("SELECT active from active").fetchone()[0])

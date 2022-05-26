import os
import sqlite3
from pathlib import Path

import discord
from discord.ext.commands import Bot

databases: dict[int, sqlite3.Connection] = {}
databases_dir_path = Path(os.path.dirname(os.path.realpath(__file__))).joinpath("databases")
current_database_version = "0.0"


def create_database_connection(guild: discord.Guild):
    """Creates a database connection to guild, populating as necessary"""
    database_path = databases_dir_path.joinpath(f"{guild.id}.sqlite3")
    databases[guild.id] = sqlite3.connect(database_path)
    if not is_valid_database(guild):
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
        CREATE TABLE preferences(
            key VARCHAR NOT NULL,
            value VARCHAR NOT NULL
        );
        """
    )
    databases[guild.id].execute(
        f"""
        INSERT INTO preferences
            (key, value)
        VALUES
            ("version", {current_database_version}),
            ("prefix", "!");
        """
    )
    databases[guild.id].commit()


def is_valid_database(guild: discord.Guild):
    try:
        database_version = (
            databases[guild.id].execute('SELECT value FROM preferences WHERE key = "version";').fetchone()
        )
        return database_version == current_database_version
    except sqlite3.OperationalError as error:
        return False


def get_prefix(bot: Bot, message: discord.Message) -> str:
    """Determines which prefix to use based on server preferences"""
    sql_table = databases[message.guild.id]
    query = "SELECT prefix FROM preferences"
    prefix = sql_table.execute(query).fetchone()
    return prefix

"""repost_bot 

This module contains a class for running a discord bot that will react on
messages when a duplicate URL is sent to a discord server.

Author: Scott Nealon
"""

import logging

import discord
from discord.ext.commands import Bot

import guild_database

logger = logging.getLogger(__name__)

bot = Bot(guild_database.get_prefix)


@bot.event
async def on_ready():
    logger.info("Ready.")

    # For each guild, open or create a database
    for guild in bot.guilds:
        guild_database.create_database_connection(guild)


@bot.event
async def on_message(message: discord.Message):
    pass
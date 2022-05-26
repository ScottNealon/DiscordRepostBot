"""repost_bot 

This module contains a class for running a discord bot that will react on
messages when a duplicate URL is sent to a discord server.

Author: Scott Nealon
"""
import logging
import time

import discord
from discord.ext.commands import Bot

import guild_database

logger = logging.getLogger(__name__)

bot = Bot(guild_database.get_prefix)

bot.ready = False


@bot.event
async def on_ready():

    # For each guild, open or create a database
    for guild in bot.guilds:
        guild_database.create_database_connection(guild)
        await guild_database.review_messages(guild, bot)

    bot.ready = True
    logger.info("Ready.")


@bot.event
async def on_message(message: discord.Message):
    # Wait until the bot is ready to read messages
    while not bot.ready:
        time.sleep(5)
    # Do nothing if inactive in server
    if not guild_database.get_active(message.guild):
        return
    # Do not trigger on self or bots
    if message.author == bot or message.author.bot:
        return

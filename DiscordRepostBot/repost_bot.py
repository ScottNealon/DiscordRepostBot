"""repost_bot 

This module contains a class for running a discord bot that will react on
messages when a duplicate URL is sent to a discord server.

Author: Scott Nealon
"""
import asyncio
import logging
from enum import Enum

import discord
import discord.ext.commands

import guild_database

logger = logging.getLogger(__name__)


class URL_STATUS(Enum):
    NEW = 0
    REPOST = 1
    REVERSE_REPOST = 2
    ALREADY_REPORTED = 3


class RepostBot(discord.ext.commands.Bot):

    ready = False

    def __init__(self, **kwargs):
        self.guild_databases: dict[int, guild_database.GuildDatabase] = {}
        intents = discord.Intents(messages=True, message_content=True, guilds=True, members=True)
        super().__init__(intents=intents, **kwargs)

    async def update_database(self, guild: discord.Guild):
        """Updates database since last online"""
        self.update_members(guild)
        await self.review_messages(guild)
        self.guild_databases[guild].commit()

    def update_members(self, guild: discord.Guild):
        """Adds and removes members from database"""
        # Retrieve all members from database
        database_member_ids = self.guild_databases[guild].members
        # Add all guild members to database
        for member in guild.members:
            if member.id not in database_member_ids:
                self.guild_databases[guild].add_member(member)

    async def review_messages(self, guild: discord.Guild):
        """Reviews all messages in guild since last update"""
        logger.info(f"Updating channels in {guild}.")
        last_updated = self.guild_databases[guild].last_updated_datetime
        blacklisted_channels = self.guild_databases[guild].blacklisted_channels
        # Iterate across all text channels in guild
        for channel in guild.channels:
            # Skip non-text channels
            if not isinstance(channel, discord.TextChannel):
                logger.info(f"{guild}/#{channel} is not a text channel.")
                continue
            # Skip blacklisted channels
            if channel.id in blacklisted_channels:
                logger.info(f"{guild}/#{channel} is blacklisted.")
                continue
            logger.info(f"{guild}/#{channel}")
            # Iterate across all messages in channel since last updated
            try:
                async for message in channel.history(after=last_updated, limit=None, oldest_first=True):
                    await self.review_message(message)
            # Catch error incase unable to access channel
            except discord.Forbidden:
                logger.warning(f"{guild}/#{channel} cannot be accessed.")

    async def review_message(self, message: discord.Message) -> bool:
        """bool : Reviews individual message to check for repost, responds TRUE if database updated"""
        # Skip any message from self, bot, or starting with recognized command
        updated = False
        if not (message.author == self or message.author.bot):
            # Search through every embed for a URL
            for embed in message.embeds:
                if embed.url == discord.Embed.Empty:
                    continue
                # Check repost status
                url_status = self.check_if_repost(embed.url, message)
                # Deal with message according to status
                if url_status == URL_STATUS.NEW:
                    self.handle_new_url(embed.url, message)
                    updated = True
                elif url_status == URL_STATUS.REPOST:
                    await self.mark_repost(embed.url, message)
                    updated = True
                elif url_status == URL_STATUS.REVERSE_REPOST:
                    self.handle_reverse_repost(embed.url, message)
                    updated = True
                elif url_status == URL_STATUS.ALREADY_REPORTED:
                    logger.debug(
                        f"Already reported URL found: {message.guild}/#{message.channel} at {message.created_at} by {message.author}: {embed.url}"
                    )
                else:
                    raise ValueError("Invalid URL status returned.")
        return updated

    def check_if_repost(self, url: str, message: discord.Message) -> int:
        """Returns whether URL is a repost or not"""
        # Check if URL has been posted before
        try:
            message_id, channel_id, query_timestamp = self.guild_databases[message.guild].get_url(url)
            # TODO: Add a case where the url has already been reported as a repost, not
            # already reported as a unique url.
            if message_id == message.id and channel_id == message.channel.id:
                return URL_STATUS.ALREADY_REPORTED
            elif query_timestamp < message.created_at.timestamp():
                return URL_STATUS.REPOST
            else:
                return URL_STATUS.REVERSE_REPOST
        # Errors if looking for url that doesn't exist
        except TypeError:
            return URL_STATUS.NEW

    @staticmethod
    def message_content_log_str(message: discord.Message, url: str) -> str:
        return f"{message.guild}/#{message.channel} at {message.created_at} by {message.author}: {url}"

    def handle_new_url(self, url: str, message: discord.Message):
        logger.debug(f"New URL found: {self.message_content_log_str(message, url)}")
        self.guild_databases[message.guild].add_url(url, message)

    async def mark_repost(self, url: str, message: discord.Message):
        logger.debug(f"Reposted URL found: {self.message_content_log_str(message, url)}")
        await message.add_reaction(self.guild_databases[message.guild].emoji)
        self.guild_databases[message.guild].add_repost(url, message)

    async def handle_reverse_repost(self, url: str, message: discord.Message):
        logger.debug(f"Reverse repost URL found: {self.message_content_log_str(message, url)}")
        # Update database with new message
        self.guild_databases[message.guild].set_url(url, message)
        # Retrieve old message
        old_message_id, old_channel_id, old_query_timestamp = self.guild_databases[message.guild].get_url(url)
        old_message: discord.Message = await message.guild.get_channel(old_channel_id).fetch_message(old_message_id)
        # Mark as repost
        await old_message.add_reaction(self.guild_databases[message.guild].emoji)
        self.guild_databases[message.guild].add_repost(url, old_message)

    def find_original_message_link(self, guild: discord.Guild, url: str) -> str:
        """Returns link to the original message that contained the URL"""
        message_id, channel_id, _ = repost_bot.guild_databases[guild].get_url(url)
        return f"https://discord.com/channels/{guild.id}/{channel_id}/{message_id}"


# Create RepostBot and add events
repost_bot = RepostBot(debug_guilds=[309873284697292802, 797250748869115904])


@repost_bot.event
async def on_ready():

    # For each guild, open or create a database and update it since last viewing.
    for guild in repost_bot.guilds:
        repost_bot.guild_databases[guild] = guild_database.GuildDatabase(guild, repost_bot)
        await repost_bot.update_database(guild)

    repost_bot.ready = True
    logger.info("on_ready() complete.")


@repost_bot.event
async def on_message(message: discord.Message):
    # Don't do anything until ready
    while not repost_bot.ready:
        await asyncio.sleep(1)
    # Do nothing if inactive in server, or on a bot
    if not repost_bot.guild_databases[message.guild].active or message.author.bot:
        return
    updated = await repost_bot.review_message(message)
    if updated:
        message_timestamp = message.created_at.timestamp()
        if message_timestamp > repost_bot.guild_databases[message.guild].last_updated:
            repost_bot.guild_databases[message.guild].last_updated = message_timestamp
        repost_bot.guild_databases[message.guild].commit()


@repost_bot.event
async def on_message_edit(old_message: discord.Message, new_message: discord.Message):
    await on_message(new_message)


@repost_bot.event
async def on_member_join(member: discord.Member):
    while not repost_bot.ready:
        await asyncio.sleep(1)
    repost_bot.guild_databases[member.guild].add_member(member)


# TODO: Remove localized guild id
@repost_bot.slash_command(guild_ids=[309873284697292802, 797250748869115904])
async def ping(context: discord.ext.commands.Context):
    await context.respond("Pong.")


@repost_bot.slash_command(
    description="Posts a link to the bot's GitHub repository.", guild_ids=[309873284697292802, 797250748869115904]
)
async def repo(context: discord.ext.commands.Context):
    await context.respond("https://github.com/ScottNealon/DiscordRepostBot")


@repost_bot.slash_command(
    description="Posts a link to the bot's privacy policy.", guild_ids=[309873284697292802, 797250748869115904]
)
async def privacy(context: discord.ext.commands.Context):
    await context.respond("https://github.com/ScottNealon/DiscordRepostBot/blob/main/PRIVACY.md")


repost_commands = discord.SlashCommandGroup("repost", "Repost related commands")


@repost_commands.command(
    description="Provides link to first message in server to post URL.",
    guild_ids=[309873284697292802, 797250748869115904],
)
async def original(
    context: discord.ext.commands.Context,
    url: discord.Option(str),
):
    await context.respond(repost_bot.find_original_message_link(context.guild, url))


repost_bot.add_application_command(repost_commands)


@repost_bot.message_command(name="Original Post", guild_ids=[309873284697292802, 797250748869115904])
async def orginal_post(context: discord.ext.commands.Context, message: discord.Message):
    responses = {}
    for embed in message.embeds:
        if embed.url == discord.Embed.Empty:
            continue
        url_status = repost_bot.check_if_repost(embed.url, message)
        if url_status == URL_STATUS.REPOST:
            responses[embed.url] = repost_bot.find_original_message_link(context.guild, embed.url)
    if len(responses) > 0:
        # TODO: Make this into a fancy embed response
        await context.respond(
            f"Original posts for URLs found on {message.jump_url} :\n\n"
            + "\n".join(f"{url} : {message_link}" for url, message_link in responses.items())
        )
    else:
        await context.respond(f"ERROR: No reposts founds on message {message.jump_url} .", ephemeral=True)

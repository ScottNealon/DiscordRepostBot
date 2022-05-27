"""repost_bot 

This module contains a class for running a discord bot that will react on
messages when a duplicate URL is sent to a discord server.

Author: Scott Nealon
"""
import asyncio
import datetime as dt
import logging
from enum import Enum

import discord
import discord.ext.commands
import humanize

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
        # Add all guild members to database
        for member in guild.members:
            if not self.guild_databases[guild].is_member(member.id):
                self.guild_databases[guild].add_member(member)

    async def review_messages(self, guild: discord.Guild):
        """Reviews all messages in guild since last update"""
        last_updated = self.guild_databases[guild].last_updated_datetime
        logger.info(f"Reading messages in {guild} since {humanize.precisedelta(dt.datetime.now() - last_updated)} ago.")
        blacklisted_channels = self.guild_databases[guild].get_blacklisted_channels()
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
            logger.info(f"Reading messages in {guild}/#{channel}")
            # Iterate across all messages in channel since last updated
            try:
                async for message in channel.history(
                    after=last_updated + dt.timedelta(microseconds=1), limit=None, oldest_first=True
                ):
                    await self.review_message(message)
            # Catch error incase unable to access channel
            except discord.Forbidden:
                logger.warning(f"{guild}/#{channel} cannot be accessed.")

    async def review_message(self, message: discord.Message) -> bool:
        """bool : Reviews individual message to check for repost, responds TRUE if database updated"""
        # Skip any message from self, bot, or starting with recognized command
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
                elif url_status == URL_STATUS.REPOST:
                    await self.mark_repost(embed.url, message)
                elif url_status == URL_STATUS.REVERSE_REPOST:
                    self.handle_reverse_repost(embed.url, message)
                elif url_status == URL_STATUS.ALREADY_REPORTED:
                    logger.debug(
                        f"Already reported URL found: {message.guild}/#{message.channel} at {message.created_at} by {message.author}: {embed.url}"
                    )
                else:
                    raise ValueError("Invalid URL status returned.")

    def check_if_repost(self, url: str, message: discord.Message) -> int:
        """Returns whether URL is a repost or not"""
        # Check if URL has been posted before
        try:
            original = self.guild_databases[message.guild].get_originals(url=url)[0]
        except IndexError:
            return URL_STATUS.NEW
        else:
            if original["messageID"] == message.id and original["channelID"] == message.channel.id:
                return URL_STATUS.ALREADY_REPORTED
            elif original["timestamp"] < message.created_at.timestamp():
                return URL_STATUS.REPOST
            else:
                return URL_STATUS.REVERSE_REPOST

    @staticmethod
    def message_content_log_str(message: discord.Message, url: str) -> str:
        return f"{message.guild}/#{message.channel} at {message.created_at} by {message.author}: {url}"

    def handle_new_url(self, url: str, message: discord.Message):
        logger.debug(f"New URL found: {self.message_content_log_str(message, url)}")
        self.guild_databases[message.guild].add_original(url, message)

    async def mark_repost(self, url: str, message: discord.Message):
        logger.debug(f"Reposted URL found: {self.message_content_log_str(message, url)}")
        await message.add_reaction(self.guild_databases[message.guild].emoji)
        self.guild_databases[message.guild].add_repost(url, message)

    async def handle_reverse_repost(self, url: str, message: discord.Message):
        logger.debug(f"Reverse repost URL found: {self.message_content_log_str(message, url)}")
        # Update database with new message
        self.guild_databases[message.guild].update_original(url, message)
        # Retrieve old message
        original = self.guild_databases[message.guild].get_originals(url=url)[0]
        old_message: discord.Message = await message.guild.get_channel(original["channelID"]).fetch_message(original["messageID"])
        # Mark as repost
        await old_message.add_reaction(self.guild_databases[message.guild].emoji)
        self.guild_databases[message.guild].add_repost(url, old_message)

    @staticmethod
    def original_message_link(guild_id: int, channel_id: int, message_id: int) -> str:
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    def message_context_markdown(
        self, guild: discord.Guild, url: str, message_id: int, channel_id: int, member_id: int, timestamp: float
    ):
        """Returns human readable context for message"""
        humanized_delta_time = humanize.naturaltime(dt.datetime.now() - dt.datetime.fromtimestamp(timestamp))
        author: discord.Member = guild.get_member(member_id)
        author_name = author.name if author else "Unknown Member"
        channel: discord.ChannelType = guild.get_channel(channel_id)
        channel_name = f"#{channel.name}" if channel else "Unknown Channel"
        orignal_message_link = self.original_message_link(guild.id, channel_id, message_id)
        return f"{humanized_delta_time} by {author_name} in [{channel_name}]({orignal_message_link})"

    def create_url_query_embed(self, guild: discord.Guild, url: str) -> discord.Embed:
        try:
            original = self.guild_databases[guild].get_originals(url=url)[0]
        except IndexError:
            raise ValueError("URL not found in database.")
        # Get all previous reposts
        reposts = self.guild_databases[guild].get_reposts(url=url)
        # Create content
        description_lines = [f"Originally posted {self.message_context_markdown(guild, *original)}", ""]
        if len(reposts) == 0:
            description_lines.append("No one has reposted this link. Congradulation!")
        else:
            description_lines.append(f"This URL has been reposted {len(reposts)} times:")
            for i, repost in enumerate(reposts):
                description_lines.append(f"{i+1}: {self.message_context_markdown(guild, *repost)}")
        # Limit total length
        description_string = "\n".join(description_lines)
        if len(description_string) > 4096:
            last_url = len(description_lines) + 1
            while len(description_string) > 4096 - 5:
                last_url -= 1
                description_string = "\n".join(description_lines[:last_url])
            description_string += "\n..."
        # Create embed
        embed = discord.Embed(title=url, description=description_string, color=discord.Colour.blurple())
        # Add users image if possible
        author = guild.get_member(original["memberID"])
        if author:
            author_image = author.guild_avatar if author.guild_avatar else author.avatar
            if author_image:
                embed.set_thumbnail(url=author_image.url)
        return embed


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
    # TODO: Handle non-guild text channels
    if not message.author.bot and repost_bot.guild_databases[message.guild].active:
        await repost_bot.review_message(message)
    # Update last updated
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
    try:
        embed = repost_bot.create_url_query_embed(context.guild, url)
        await context.respond(embed=embed)
    except ValueError:
        await context.respond(f"ERROR: Unable to find previous post of {url}", ephemeral=True)


repost_bot.add_application_command(repost_commands)


@repost_bot.message_command(name="Original Post", guild_ids=[309873284697292802, 797250748869115904])
async def orginal_post(context: discord.ext.commands.Context, message: discord.Message):
    responded = False
    for embed in message.embeds:
        if embed.url == discord.Embed.Empty:
            continue
        try:
            embed = repost_bot.create_url_query_embed(context.guild, embed.url)
            await context.respond(embed=embed)
            responded = True
        except ValueError:
            pass
    if not responded:
        await context.respond(f"ERROR: No reposts founds on message.", ephemeral=True)

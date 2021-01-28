'''protestbot 

This module contains a class for running a discord bot that will react on
messages when a duplicate URL is sent to a discord server.

Author: Scott Nealon
'''

from datetime import datetime, timedelta, timezone
import json
import logging
import logging.config
import re
import os

from dateutil.parser import parse
import discord
import schedule
import urlextract

from continuousScheduler import ContinuousScheduler


log = logging.getLogger(__name__)


class ProtestBot(discord.Client):

    def __init__(self, **kwargs):

        # Notifies intent to manage members. Used to get list of all members.
        # WARNING: Must be enabled at https://discord.com/developers/applications/ under Server Members Intent
        intents = discord.Intents.default()
        intents.members = True

        super().__init__(intents=intents, **kwargs)

        # Variable setup
        self.URLextractor = urlextract.URLExtract()
        self.ready = False
        self.db = {}


    async def on_ready(self):
        '''Called when bot has finished communicating with Discord. Sets up databases '''

        log.info('Logged in as {0}'.format(self.user))

        # Create or load protest databases for all guilds
        log.info('Number of active guilds: {0}'.format(len(self.guilds)))
        for guild in self.guilds:
            await self.get_protest_database(guild)

        # Setup scheduler
        self.schedule_periodic_saving()

        # Set activity
        await self.set_activity(discord.ActivityType.listening, '$ProtestHelp')

        self.ready = True
        log.info('Bot setup complete.')


    async def get_protest_database(self, guild: discord.Guild):
        '''Either retrieves protest database from JSON file or creates a new one'''

        # Check if database directory exits. Create it if not.
        dir_path = os.path.dirname(os.path.realpath(__file__))
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        # Load database JSON file if it exists
        file_name = os.path.join(dir_path, '{0}.json'.format(guild.id))
        if os.path.exists(file_name):
            self.db[guild.id] = self.read_database(guild.id)
    
            # Update guild only if actilve
            if self.db[guild.id]['active']:
                await self.update_guild_database(guild)

        # If no database JSON file exists, create new one.
        else:
            await self.new_guild_database(guild)


    async def update_guild_database(self, guild: discord.Guild, after_time=None):
        '''Updates existing guild database'''

        log.info('Updating {0} database...'.format(guild.name))
        log.info('Last updated: {0}'.format(self.db[guild.id]['last_update']))

        # Create entries for any new members
        self.add_members(guild)

        # If after_time not provided, update since last update.
        if after_time is None:
            after_time = datetime.strptime(self.db[guild.id]['last_update'], '%Y/%m/%d %H:%M:%S %Z')#.replace(tzinfo=timezone.utc).replace(tzinfo=None)

        # Update missing messages
        num_old_urls = len(self.db[guild.id]['URLs'])
        await self.search_channels(guild, after_time)
        log.info('{0} Unique URLs added.'.format(len(self.db[guild.id]['URLs']) - num_old_urls))

        # Push back first update if newest
        first_update_date = datetime.strptime(self.db[guild.id]['first_update'], '%Y/%m/%d %H:%M:%S %Z')
        if first_update_date > after_time:
            self.db[guild.id]['first_update'] = after_time.strftime('%Y/%m/%d %H:%M:%S %Z')

        # Save database to file
        self.save_database(guild.id)
        log.info('{0} database updated succesfully.'.format(guild.name))


    async def new_guild_database(self, guild: discord.Guild):
        '''Creates new database entry for guild'''

        log.info('Creating {0} database...'.format(guild.name))
        
        # Create empty database
        self.db[guild.id] = {
            'guild_name': guild.name,
            'guild_id': guild.id,
            'active': True,
            'channel_blacklist': [],
            'emoji': '♻️',
            'first_update': datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S %Z'),
            'last_update': datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S %Z'),
            'URL_blacklist': ['https://www.youtube.com/watch?v=8kkBseVTUow&ab_channel=AllGasNoBrakes'],
            'members': {},
            'URLs': {}
            }
        
        # Create entries for all members
        self.add_members(guild)

        # Save database to file
        self.save_database(guild.id)
        log.info('{0} database created succesfully.'.format(guild.name))


    def add_members(self, guild: discord.Guild):
        '''Creates empty db entries for all members not already in db'''
        for member in guild.members:
            self.db[guild.id]['members'].setdefault(member.id, {
                'unique_URLs': {},
                'repost_URLs': {}
            })


    async def on_message(self, message: discord.Message):
        '''Runs every time a message is recieved'''

        # Don't start if bot is not ready
        if not self.ready: return

        # Ignore messages from bot or other bots
        if message.author == self.user: return
        if message.author.bot: return

        # If message starts with $Protest, run controls. If something happens, don't continue.
        if message.content.lower().startswith('$protest'):
            await self.bot_controls(message)
            return

        # Ignore channel if server or channel is inactive
        if not self.db[message.guild.id]['active'] or message.channel.id in self.db[message.guild.id]['channel_blacklist']: return       

        # Check message and update
        await self.check_message(message)


    async def search_channels(self, guild: discord.Guild, after_time):
        '''Run through all messages in guild after after_time'''

        # Iterate across all text channels in guild
        for i, channel in enumerate(channel for channel in guild.channels):
            log.info('Channel {0}: {1}'.format(i + 1, channel))

            # Skip text channels
            if not isinstance(channel, discord.TextChannel):
                log.debug('Channel {0} is not a Text Channel.'.format(channel))
                continue

            # Skip blacklisted channels
            if channel.id in self.db[guild.id]['channel_blacklist']:
                log.warning('Channel {0} is blacklisted.'.format(channel))
                continue

            # Iterate across all messages in channel since time_ago
            try:
                async for message in channel.history(after=after_time.replace(tzinfo=None), limit=None, oldest_first=True):
                    await self.check_message(message)

            # Catch error incase unable to access channel
            except discord.Forbidden:
                log.error('Channel {0} cannot be accessed.'.format(channel))
                pass


    async def check_message(self, message: discord.Message):
        '''Checks a single message for URLs'''

        # Skip messages from self or bot, or a $protest comm
        if message.author == self.user: return
        if message.author.bot: return
        if message.content.lower().startswith('$protest'): return

        # Find message urls and interate through all non-blacklisted urls
        message_urls = self.URLextractor.find_urls(message.content)
        for message_url in message_urls:
            if message_url not in self.db[message.guild.id]['URL_blacklist']:

                # If url is unique, add to database
                if message_url not in self.db[message.guild.id]['URLs']:
                    self.db[message.guild.id]['URLs'][message_url] = {'user_id': message.author.id}
                    try:
                        self.db[message.guild.id]['members'][message.author.id]['unique_URLs'][message_url] = {'channel_id': message.channel.id, 'message_id': message.id}
                    except KeyError:
                        self.db[message.guild.id]['members'].setdefault(message.author.id, {'unique_URLs': {}, 'repost_URLs': {}})
                        self.db[message.guild.id]['members'][message.author.id]['unique_URLs'][message_url] = {'channel_id': message.channel.id, 'message_id': message.id}
                    log.debug('New URL found in #{0} at {1:%Y-%m-%d %H:%M:%S} by {2}: {3}'.format(message.channel, message.created_at, message.author, message_url))

                # If url is not unique, fetch old message
                else:
                    old_user_id = self.db[message.guild.id]['URLs'][message_url]['user_id']
                    old_channel_id = self.db[message.guild.id]['members'][old_user_id]['unique_URLs'][message_url]['channel_id']
                    old_message_id = self.db[message.guild.id]['members'][old_user_id]['unique_URLs'][message_url]['message_id']
                    old_channel = message.guild.get_channel(old_channel_id)
                    old_message = await old_channel.fetch_message(old_message_id)

                    # If message is a repost, shame the new reposter
                    if message.created_at > old_message.created_at:
                        await message.add_reaction(self.db[message.guild.id]['emoji'])
                        try:
                            if message_url in self.db[message.guild.id]['members'][message.author.id]['repost_URLs'].keys():
                                self.db[message.guild.id]['members'][message.author.id]['repost_URLs'][message_url]['count'] += 1
                            else:
                                self.db[message.guild.id]['members'][message.author.id]['repost_URLs'][message_url] = {'channel_id': message.channel.id, 'message_id': message.id, 'count': 1}
                        except KeyError:
                            self.db[message.guild.id]['members'].setdefault(message.author.id, {'unique_URLs': {}, 'repost_URLs': {}})
                            if message_url in self.db[message.guild.id]['members'][message.author.id]['repost_URLs'].keys():
                                self.db[message.guild.id]['members'][message.author.id]['repost_URLs'][message_url]['count'] += 1
                            else:
                                self.db[message.guild.id]['members'][message.author.id]['repost_URLs'][message_url] = {'channel_id': message.channel.id, 'message_id': message.id, 'count': 1}
                        log.info('Duplicate URL Found in #{0} at {1:%Y-%m-%d %H:%M:%S} by {2}: {3}'.format(message.channel, message.created_at, message.author, message_url))

                    # If message is identical, do nothing.
                    elif message.id == old_message.id:
                        continue

                    # If message is a reverse repost, shame the old reposter and update url records
                    else:
                        await old_message.add_reaction(self.db[message.guild.id]['emoji'])
                        if message_url in self.db[message.guild.id]['members'][old_user_id]['repost_URLs'].keys():
                            self.db[message.guild.id]['members'][old_user_id]['repost_URLs'][message_url]['count'] += 1
                        else:
                            self.db[message.guild.id]['members'][old_user_id]['repost_URLs'][message_url] = {'channel_id': old_message.channel.id, 'message_id': old_message.id, 'count': 1}
                        self.db[message.guild.id]['members'][old_user_id]['unique_URLs'].pop(message_url, None)
                        self.db[message.guild.id]['URLs'][message_url]['user_id'] = message.author.id
                        try:
                            self.db[message.guild.id]['members'][message.author.id]['unique_URLs'][message_url] = {'channel_id': message.channel.id, 'message_id': message.id}
                        except KeyError:
                            self.db[message.guild.id]['members'].setdefault(message.author.id, {'unique_URLs': {}, 'repost_URLs': {}})
                            self.db[message.guild.id]['members'][message.author.id]['unique_URLs'][message_url] = {'channel_id': message.channel.id, 'message_id': message.id}
                        log.warning('Reverse repost found: {0}'.format(message_url))
                        log.warning('Original message in #{0} at {1:%Y-%m-%d %H:%M:%S} by {2}.'.format(message.channel, message.created_at, message.author))
                        log.warning('Reposted message in #{0} at {1:%Y-%m-%d %H:%M:%S} by {2}.'.format(old_message.channel, old_message.created_at, old_message.author))

            # If URL is blacklisted, log warning.
            else:
                log.warning('Blacklisted url posted in #{0} at {1:%Y-%m-%d %H:%M:%S} by {2}: {3}'.format(message.channel, message.created_at, message.author, message_url))
            
            # Update last-updated
            self.db[message.guild.id]['last_update'] = max(
                datetime.strptime(self.db[message.guild.id]['last_update'], '%Y/%m/%d %H:%M:%S %Z'),
                message.created_at
                ).replace(tzinfo=timezone.utc).strftime('%Y/%m/%d %H:%M:%S %Z')


    async def bot_controls(self, message: discord.Message):

        log.info('Command recieved: {0} in {1}/#{2} by {3}'.format(message.content, message.guild, message.channel, message.author))

        # Responds whether the bot is active in the server
        if message.content.lower() == '$protestactive':
            if self.db[message.guild.id]['active']:
                await message.add_reaction('✅')
                log.debug('Command executed: Bot is active in {0}.'.format(message.guild))
            else:
                await message.add_reaction('❌')
                log.warning('Command not executed: Bot is NOT active in {0}.'.format(message.guild))

        # List channels in server that are blacklisted.
        elif message.content.lower() == '$protestchannelblacklist':
            if len(self.db[message.guild.id]['channel_blacklist']) == 0:
                blacklisted = 'None'
            else:
                blacklisted = '#' + ', #'.join(message.guild.get_channel(int(channel_id)).name for channel_id in self.db[message.guild.id]['channel_blacklist'])
            await message.channel.send('Blacklisted channels: {0}'.format(blacklisted))
            log.debug('Command executed: List of blacklisted channels posted in {0}/#{1}.'.format(message.guild, message.channel))

        # Check number of urls
        elif message.content.lower() == '$protestcount':
            await message.channel.send('We are monitoring {0} protests (unique URLs).'.format(len(self.db[message.guild.id]['URLs'])))
            log.debug('Command executed: Number of urls ({0}) posted in {1}/#{2}'.format(len(self.db[message.guild.id]['URLs']), message.guild, message.channel))

        # TODO: Implement
        # Posts link to list of all URLs.
        elif message.content.lower() == '$protestlist':
            await message.channel.send('URL is dead. Bug Scott if you care enough.')
            log.warning('Command not executed: Link to list of URLs NOT posted.')

        # Post original youtube video
        elif message.content.lower() == '$protestoriginalvideo':
            await message.channel.send('https://www.youtube.com/watch?v=8kkBseVTUow&ab_channel=AllGasNoBrakes')
            log.debug('Command executed: Original protest link posted in {0}/#{1}'.format(message.guild, message.channel))

            # Post urls that don't count as reposts.
        elif message.content.lower() == '$protesturlblacklist':
            await message.channel.send('Blacklisted URLs:\n' + '\n'.join(blacklisted_url for blacklisted_url in self.db[message.guild.id]['URL_blacklist']))
            log.debug('Command executed: Blacklisted urls posted in {0}/#{1}.'.format(message.guild, message.channel))

        # TODO: Implement
        # Post number of protets a user has attended (# of reposts).
        elif message.content.lower() == '$protestshame':
            await message.add_reaction('🔄')

            # Calculate number of reposts for each user, appending if they have reposts
            shame_dict = {}
            for member_id, member_db in self.db[message.guild.id]['members'].items():
                num_reposts = sum([url_dict['count'] for url_dict in member_db['repost_URLs'].values()])
                # num_reports = len(member_db['repost_URLs'])
                if num_reposts > 0:
                    member = await message.guild.fetch_member(member_id)
                    shame_dict[member.nick] = num_reposts

            # Sort user database by # of reposts
            sorted_dict = {k: v for k, v in sorted(shame_dict.items(), key=lambda item: item[1], reverse=True)}
            
            message_str = 'Number of protests attended since {0}:\n'.format(self.db[message.guild.id]['first_update']) + \
                '\n'.join('{0} - {1}'.format(reposts, user_nick) for (user_nick, reposts) in sorted_dict.items())
            await message.channel.send(message_str)
            await message.remove_reaction('🔄', self.user)
            log.debug('Command executed: Shame list posted in {0}/#{1}'.format(message.guild, message.channel))

        # Post details of single user's protests
        elif message.content.lower().startswith('$protestshame'):
            await message.add_reaction('🔄')
            
            name = message.content[14:]
            member = message.guild.get_member_named(name)
            if member is None:
                if re.sub('[<@!>]', '', name).isdigit():
                    member = message.guild.get_member(int(re.sub('[<@!>]', '', name)))

            if member is not None:
                num_reposts = sum([url_dict['count'] for url_dict in self.db[message.guild.id]['members'][member.id]['repost_URLs'].values()])
                num_unique = len(self.db[message.guild.id]['members'][member.id]['unique_URLs'])
                num_total = num_reposts + num_unique
                repost_rate = num_reposts / num_total

                message_str = ('User: {0}\n' + 
                    'Number of URLs Posted: {1}\n' +
                    'Number of URLs Reposted: {2}\n' +
                    'Repost Rate: {3:.2%}').format(member.nick, num_total, num_reposts, repost_rate)
                await message.remove_reaction('🔄', self.user)
                await message.channel.send(message_str)
                log.info('Command executed: User {0} shamed in {1}/#{2}'.format(member.name, message.guild, message.channel))
            else:
                await message.remove_reaction('🔄', self.user)
                await message.add_reaction('❌')
                log.warning('Command not executed: User {0} not found in {1}.'.format(name, message.guild))


        # If asking for help or posted $protest and didn't fit anything else they're authorized to access, post help.
        elif message.content.lower() == '$protesthelp' or (not message.author.guild_permissions.manage_guild and not message.author.name == 'UnrealArchon#5847'):
            await message.channel.send(
                'All users:\n' +
                '$ProtestActive: Responds whether the bot is active in this server.\n' +
                '$ProtestCount: Post number of unique URLs in database.\n' +
                '$ProtestShame: Post number of protets users have attended in an ordered list (# of reposts).\n' +
                '$ProtestShame <User>: Post details of single user\'s protests.\n' +
                '$ProtestList: Posts link to all posted URLs.\n' +
                '$ProtestOriginalVideo: Posts original Coronavirus Lockdown Protest.\n' +
                '$ProtestChannelBlacklist: Post channels in server that are blacklisted.\n' +
                '$ProtestURLBlacklist: Post URLs that don\'t count as reposts.\n' +
                '$ProtestHelp: Post help text for commands.\n' +
                '$ProtestHelpManager: Post advanced help text for manager commands. Server managers only.'
            )
            log.info('Command executed: Help posted in {0}/#{1}.'.format(message.guild, message.channel))

        ### ALL COMMANDS UNDER HERE REQUIRE MANAGE_GUILD PERMISSIONS ###

        elif message.content.startswith('$ProtestHelpManager'):
            await message.channel.send(
                'Server Managers:\n' +
                '$ProtestSetEmoji: Set new primary emoji.\n' +
                '$ProtestRemoveReactions: Removes reactions from all messages.\n' +
                '$ProtestChannelStop: Stop reacting and indexing messages in this channel.\n' +
                '$ProtestChannelResume: Continue reacting and indexing messages in this channel.\n' +
                '$ProtestURLStop <URLs>: Stop counting URLs as a repost.\n' +
                '$ProtestURLResume <URLs>: Continue counting URLs as a repost.\n' +
                '$ProtestServerStop: Stop reacting to messages in this server.\n' + 
                '$ProtestServerResume: Continue reacting to messages in this server.\n' +
                '$ProtestSave: Saves database to file.\n' +
                '$ProtestUpdate: Check all URLs since last update.\n' +
                '$ProtestUpdate <int>: Check all URLs in the last <int> days. WARNING: Resets shame counter.\n' +
                '$ProtestResetDatabase: DANGER! Resets bot database for server.'
            )
            log.info('Command executed: Manager help posted in {0}/#{1}.'.format(message.guild, message.channel))

        elif message.content.lower() == '$protestsave':
            self.save_database(message.guild.id)
            log.info('Command executed: {0} database saved to file.'.format(message.guild))
            await message.add_reaction('✅')

        # Set new primary emoji
        elif message.content.lower().startswith('$protestsetemoji'):
            message_emojis = re.findall(r'<:\w*:\d*>', message.content)
            if len(message_emojis) > 0:
                self.db[message.guild.id]['emoji'] = message_emojis[0]
                log.debug('Command executed: Emoji set to {0}.'.format(self.db[message.guild.id]['emoji']))
            else:
                log.warning('Command not executed: No emojis found.')
            await message.add_reaction(self.db[message.guild.id]['emoji'])

        # Remove reactions from all messages
        elif message.content.lower().startswith('$protestremovereactions'):
            log.warning('Command executing: Removing all reactions.')

            # Iterate through every text channel
            for i, channel in enumerate(channel for channel in message.guild.channels):
                log.info('Channel {0}: {1}'.format(i + 1, channel))
                if not isinstance(channel, discord.TextChannel):
                    log.debug('Channel {0} is not a Text Channel.'.format(channel))
                    continue

                # Iterate through every message and reactions, removing those made by bot
                try:
                    async for historic_message in channel.history(limit=None):
                        for reaction in historic_message.reactions:
                            if reaction.me:
                                await historic_message.remove_reaction(reaction.emoji, self.user)

                # Catch error incase unable to access channel
                except discord.Forbidden:
                    log.error('Channel {0} cannot be accessed.'.format(channel))
                    pass

            await message.add_reaction(self.db[message.guild.id]['emoji'])
            log.warning('Command executed: All reactions removed.')

        # Continue reacting and indexing messages in this channel.
        elif message.content.lower() == '$protestchannelresume':
            if message.channel.id in self.db[message.guild.id]['channel_blacklist']:
                self.db[message.guild.id]['channel_blacklist'].remove(message.channel.id)
                self.save_database(message.guild.id)
                log.debug('Command executed: {0} removed from {1} blacklist.'.format(message.channel, message.guild))
            else:
                log.warning('Command not executed: {0} is not on the {1} blacklist.'.format(message.channel, message.guild))
            await message.add_reaction('✅')
            
        # Stop reacting and indexing messages in this channel.
        elif message.content.lower() == '$protestchannelstop':
            if message.channel.id not in self.db[message.guild.id]['channel_blacklist']:
                self.db[message.guild.id]['channel_blacklist'].append(message.channel.id)
                self.save_database(message.guild.id)
                log.debug('Command executed: {0} added to {1} blacklist.'.format(message.channel, message.guild))
            else:
                log.warning('Command not executed: {0} is already on the {1} blacklist'.format(message.channel, message.guild))
            await message.add_reaction('✅')

        elif message.content.lower().startswith('$protestresetdatabase'):
            if message.content.lower() == '$protestresetdatabase confirm':
                await message.add_reaction('🔄')
                await self.new_guild_database(message.guild)
                await message.remove_reaction('🔄', self.user)
                await message.add_reaction('✅')
                log.warning('Command executed: {0} database reset.'.format(message.guild))
            else:
                await message.channel.send('WARNING: Attempting to delete bot\'s server database. To confirm, post \"$ProtestResetDatabase confirm\"')
                log.warning('Command not executed: {0} database reset request made without confirmation.'.format(message.guild))

        # Turn bot on for server
        elif message.content.lower() == '$protestserverresume':
            if not self.db[message.guild.id]['active']:
                self.db[message.guild.id]['active'] = True
                self.save_database(message.guild.id)
                log.debug('Command executed: Bot activated in {0}.'.format(message.guild))
            else:
                log.warning('Command not executed: Bot already active in {0}.'.format(message.guild))
            await message.add_reaction('✅')

        # Turn bot off for server
        elif message.content.lower() == '$protestserverstop':
            if self.db[message.guild.id]['active']:
                self.db[message.guild.id]['active'] = False
                self.save_database(message.guild.id)
                log.warning('Command executed: Bot deactivated in {0}.'.format(message.guild))
            else:
                log.warning('Command not executed: Bot already deactivated in {0}'.format(message.guild))
            await message.add_reaction('✅')

        # Update database
        elif message.content.lower().startswith('$protestupdate'):
            await message.add_reaction('🔄')
            # If command contained number of days, update up to that many days ago.
            try:
                rest_of_message = message.content.lower().split('$protestupdate',1)[1]
                after_time = parse(rest_of_message)
                log.warning('Command update: Updating {0} database since {1} by command.'.format(message.guild.name, after_time))
                await self.update_guild_database(message.guild, after_time)
            except(ValueError):
                log.warning('Command update: Updating {0} database since {1} by command.'.format(message.guild.name, self.db[message.guild.id]['last_update']))
                await self.update_guild_database(message.guild)
            await message.remove_reaction('🔄', self.user)
            await message.add_reaction('✅')
            log.warning('Command executed: {0} database update by command completed.'.format(message.guild.name))

        # Continue counting URLs as a repost.
        elif message.content.lower().startswith('$protesturlresume'):
            whitelist_URLs = self.URLextractor.find_urls(message.content)
            if len(whitelist_URLs) > 0:
                for whitelist_URL in whitelist_URLs:
                    self.db[message.guild.id]['URL_blacklist'].remove(whitelist_URL)
                self.save_database(message.guild.id)
                log.info('Command executed: URLs removed from {0} blacklist.'.format(message.guild.name))
            else:
                log.warning('Command not executed: No URLs provided.')
            await message.add_reaction('✅')

        # Stop counting URLs as a repost.
        elif message.content.lower().startswith('$protesturlstop'):
            blacklist_URLs = self.URLextractor.find_urls(message.content)
            if len(blacklist_URLs) > 0:
                for blacklist_URL in blacklist_URLs:
                    self.db[message.guild.id]['URL_blacklist'].append(blacklist_URL)
                self.save_database(message.guild.id)
                log.info('Command executed: URLs added from {0} blacklist'.format(message.guild.name))
            else:
                log.warning('Command not executed: No URLs provided.')
            await message.add_reaction('✅')

        # If nothing, recognize erroneous command.
        else:
            await message.add_reaction('❓')
            log.warning('Command not executed: Erroneous command recieved.')


    def read_database(self, guild_id):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        file_name = os.path.join(dir_path, '{0}.json'.format(guild_id))
        with open(file_name, 'r') as json_file:
            guild_db = json.load(json_file, object_hook=jsonKeys2int)
        log.info('{0} database read from file.'.format(guild_db['guild_name']))
        return guild_db


    def save_database(self, guild_id):
        json_str = json.dumps(self.db[guild_id], indent=4)
        dir_path = os.path.dirname(os.path.realpath(__file__))
        file_name = os.path.join(dir_path, '{0}.json'.format(guild_id))
        with open(file_name, 'w') as json_file:
            json_file.write(json_str)

        log.info('{0} database saved to file.'.format(self.db[guild_id]['guild_name']))


    async def set_activity(self, activity, name):
        await self.change_presence(activity=discord.Activity(type=activity, name=name))


    def schedule_periodic_saving(self):
        self.bot_schedule = ContinuousScheduler()
        self.bot_schedule.every(15).minutes.do(self.save_all_databases)
        self.bot_schedule_stopper = self.bot_schedule.run_continuously()


    def save_all_databases(self):
        log.info('Performing scheduled database saving.')
        for guild in self.guilds:
            self.save_database(guild.id)


def jsonKeys2int(x):
    '''Converts any key that is a digit to an int. https://stackoverflow.com/a/34346202'''
    if isinstance(x, dict):
        return {(int(k) if k.isdigit() else k):v for k, v in x.items()}
    else:
        return x
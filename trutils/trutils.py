import datetime

try:
    from google.cloud import vision
except:
    print('google cloud vision not found, some features unavailable')

from rpadutils.rpadutils import *
from rpadutils.rpadutils import CogSettings
from redbot.core import checks, modlog
from redbot.core.utils.chat_formatting import *

import discord

GETMIRU_HELP = """
The new public Miru is open for invite to any server: personal, private, secret-handshake-entry-only, etc
Unlike the private Miru used by larger community servers, public Miru has lower stability requirements, 
so I will install a variety of random entertainment plugins.

To invite public Miru to your server, use the following link:
https://discordapp.com/oauth2/authorize?client_id=296443771229569026&scope=bot

The following commands might come in handy:
`^modhelp`       - information on how to set up Miru's moderation commands
`^userhelp`     - a user-focused guide to Miru's commands
`^help`             - the full list of Miru commands

If you want to be notified of updates to Miru, suggest features, or ask for help, join the Miru Support server:
https://discord.gg/zB4QHgn
"""

USER_HELP = """
Bot user help
This command gives you an overview of the most commonly used user-focused
commands, with an emphasis on the ones unique to this bot.

Join the Miru Support Server for info, update, and bot support:
https://discord.gg/zB4QHgn

Use ^help to get a full list of help commands. Execute any command with no
arguments to get more details on how they work.

Info commands:
^credits   some info about the bot
^donate    info on how to donate to cover hosting fees
^userhelp  this message
^modhelp   bot help specifically for mods

General:
^pad             lists the pad-specific global commands
^padfaq          lists pad-specific FAQ commands
^boards          lists common leader optimal board commands
^glossary        looks up a pad term in the glossary
^customcommands  lists the custom commands added by the administrators of your server
^memes           works the same way, but is restricted per-server to a privileged memer-only group
^serverinfo      stats for the current server
^userinfo        stats for a specific user

Events:
^[events|eventsna]  Prints pending/active PAD events for NA
^eventsjp           Prints pending/active PAD events for JP

Monster Info:
^id        search for a monster by ID, full name, nickname, etc
^idz       text-only version if id (the legacy version, for mobile users)
^helpid    gets more info on how monster lookup works, including the nickname submission link
^pantheon  given a monster, print all the members of the pantheon
^pic       prints a link to a a monster image on puzzledragonx, which discord will inline
^img       same as pic

Profile:
Miru will store your personal PAD details, and provide them on request.
Use the series of commands starting with ^profile to configure your own profile.

Use one of the following commands to retrieve data.
^idme            print your profile to the current channel
^idfor           get profile data for a specific user
^idto            have Miru DM your profile to a user
^profile search  search the list of configured (visible) profiles

Time conversion:
^time    get the current time in a different timezone
^timeto  calculate the how long until another time in another timezone

Translation:
^[jpen|jpus|jaen|jaus] <text>  translate text from japanese to english
"""

MOD_HELP = """
Bot Moderator Help
~~~~~~~~~~~~~~~~~~~~~~

If you need help setting your server up, feel free to ping me (tactical_retreat).

Miru is a set of plugins inside the Red Discord bot, running on discord.py. There
are some custom ones, but a lot of them are generic to all Red Discord bots, so
things you've used elsewhere will probably also work here.

If there is a feature you're missing, let me know and I can check to see if it's
already available in some public plugin. If not, and I think it's valuable, I might
write it.

~~~~~~~~~~~~~~~~~~~~~~

Check out the ^help command from inside your server. You'll see a wider list of
commands than normal users do.

If you've just added Miru to your server, start with the ^modset command. You
might want to configure an Admin and a Mod role (they can be the same thing).

~~~~~~~~~~~~~~~~~~~~~~
Interesting features
~~~~~~~~~~~~~~~~~~~~~~

Self applied roles:
You can configure which roles a user can add to themself using ^selfrole via ^adminset

Message logs:
Discord doesn't save deleted/edited messages anywhere. Using ^exlog you can pull
messages for a user, channel, or search for a term.

Contrast this with ^logs which uses the Discord API, and can retrieve a significantly
larger log history, but it reflects what you would see in Discord by scrolling back.

Auto Moderation:
The ^automod2 command allows you to configure a set of rules (defined as regular expressions)
that match messages. You can then apply these rules as either a blacklist or a whitelist to
a specific channel. This allows you to force users to format their messages a specific way,
or to prevent them from saying certain things (the bot deletes violators, and notifies them
via DM).

Bad user tools:
Allows you to specify a set of roles that are applied as punishments to users, generally
restricting them from seeing or speaking in certain channels. If a punishment role is
applied to a user, the last 10 things they said (and where they said it) are recorded, and
a strike is added to their record.

You can configure a channel where Miru will log when these moderation events occur, and ping
@here asking for an explanation. She will also track when a user with a strike leaves the
server, and when they rejoin the server (as this is generally done to evade negative roles).

Custom commands:
Miru supports three types of custom commands, you can find the list of associated commands via ^help.
* CustomCommands: Added by server mods, executable by anyone
* Memes: Added by server mods, executable only by people with a specific Role (configured by mods)
* Pad: Added by specific users (configured by tactical_retreat) and executable by users in any server

PAD Event announcement:
You can use the ^padevents commands to configure PAD related announcements for specific channels.

Using '^padevents addchannel NA' you can enable guerrilla announcements for the current channel.
Using '^padevents addchanneldaily NA' you can enable a dump of the currently active events,
including things like skillup rate, daily descends, daily guerrillas, etc. This typically ticks
over twice daily.

Use the rmchannel* commands to disable those subscriptions. ^padevents listchannels shows the
set of subscriptions for the current server. You can also subscribe to JP events if desired.

Limiting command execution:
The '^p' command can be used to prevent users from executing specific commands on the server,
in specific channels, or unless they have specific roles. Read the documentation carefully.
"""


class TrUtils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = TrUtilsSettings("trutils")

    @commands.command()
    async def revertname(self, ctx):
        """Unsets your nickname"""
        await ctx.author.edit(nick=None)
        await ctx.send(inline('Done'))

    @commands.command()
    @checks.mod_or_permissions(manage_guild=True)
    async def editmsg(self, ctx, channel: discord.TextChannel, msg_id: int, *, new_msg: str):
        """Given a channel and an ID for a message printed in that channel, replaces it.

        To find a message ID, enable developer mode in Discord settings and
        click the ... on a message.
        """
        try:
            msg = await channel.fetch_message(msg_id)
        except discord.NotFound:
            await ctx.send(inline('Cannot find that message, check the channel and message id'))
            return
        except discord.Forbidden:
            await ctx.send(inline('No permissions to do that'))
            return
        if msg.author.id != self.bot.user.id:
            await ctx.send(inline('Can only edit messages I own'))
            return

        await msg.edit(content = new_msg)
        await ctx.send(inline('done'))

    @commands.command()
    @checks.mod_or_permissions(manage_guild=True)
    async def dumpchannel(self, ctx, channel: discord.TextChannel, msg_id: int=None):
        """Given a channel and an ID for a message printed in that channel, dumps it 
        boxed with formatting escaped and some issues cleaned up.

        To find a message ID, enable developer mode in Discord settings and
        click the ... on a message.
        """
        await self._dump(ctx, channel, msg_id)

    @commands.command()
    async def dumpmsg(self, ctx, msg_id: int=None):
        """Given an ID for a message printed in the current channel, dumps it
        boxed with formatting escaped and some issues cleaned up.

        To find a message ID, enable developer mode in Discord settings and
        click the ... on a message.
        """
        await self._dump(ctx, ctx.channel, msg_id)

    async def _dump(self, ctx, channel: discord.TextChannel=None, msg_id: int=None):
        if msg_id:
            msg = await channel.fetch_message(msg_id)
        else:
            msg_limit = 2 if channel == ctx.channel else 1
            async for message in channel.history(limit=msg_limit):
                msg = message
        content = msg.content.strip()
        content = re.sub(r'<(:[0-9a-z_]+:)\d{18}>', r'\1', content, flags=re.IGNORECASE)
        content = box(content.replace('`', u'\u200b`'))
        await ctx.send(content)

    @commands.command()
    async def dumpmsgexact(self, ctx, msg_id: int):
        """Given an ID for a message printed in the current channel, dumps it 
        boxed with formatting escaped.

        To find a message ID, enable developer mode in Discord settings and
        click the ... on a message.
        """
        msg = await ctx.channel.fetch_message(msg_id)
        content = msg.content.strip()
        content = box(content.replace('`', u'\u200b`'))
        await ctx.send(content)

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def imagecopy(self, ctx, source_channel: discord.TextChannel, dest_channel: discord.TextChannel):
        self.settings.setImageCopy(ctx.guild.id, source_channel.id, dest_channel.id)
        await ctx.send('`done`')

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def clearimagecopy(self, ctx, channel: discord.TextChannel):
        self.settings.clearImageCopy(ctx.guild.id, channel.id)
        await ctx.send('`done`')

    async def copy_image_to_channel(self, img_url, author_name, channel_name, img_copy_channel_id):
        embed = discord.Embed()
        embed.set_footer(text='Posted by {} in {}'.format(author_name, channel_name))
        embed.set_image(url=img_url)

        try:
            await self.bot.get_channel(img_copy_channel_id).send(embed=embed)
        except Exception as e:
            print('Failed to copy msg to', img_copy_channel_id, e)

    async def copy_attachment_to_channel(self, msg, in_attachment, img_copy_channel_id):
        embed = discord.Embed()
        embed.set_footer(text='Posted by {} in {}'.format(msg.author.name, msg.channel.name))
        embed.set_image(url=in_attachment.url)
        try:
            await self.bot.get_channel(img_copy_channel_id).send(embed=embed)
        except Exception as e:
            print('Failed to copy attachment to', img_copy_channel_id, e)

    async def copy_embed_to_channel(self, msg, in_embed, img_copy_channel_id):
        embed = discord.Embed()
        embed.description = in_embed.url
        embed.title = in_embed.title if hasattr(in_embed, 'title') else None
        embed.set_image(url=in_embed.thumbnail.proxy_url)
        embed.set_footer(text='Posted by {} in {}'.format(msg.author.name, msg.channel.name))
        try:
            await self.bot.get_channel(img_copy_channel_id).send(embed=embed)
        except Exception as e:
            print('Failed to copy embed to', img_copy_channel_id, e)

    @commands.Cog.listener('on_message')
    async def on_imgcopy_message(self, message):
        if message.author.id == self.bot.user.id or isinstance(message.channel, discord.abc.PrivateChannel):
            return

        img_copy_channel_id = self.settings.getImageCopy(message.guild.id, message.channel.id)
        if img_copy_channel_id is None:
            return

        if message.attachments:
            for a in message.attachments:
                await self.copy_attachment_to_channel(message, a, img_copy_channel_id)
            return

        if message.embeds:
            for e in message.embeds:
                await self.copy_embed_to_channel(message, e, img_copy_channel_id)
            return

    @commands.Cog.listener('on_message_edit')
    async def on_imgcopy_edit_message(self, old_message, new_message):
        if len(old_message.embeds) == 0 and len(new_message.embeds) > 0:
            await self.on_imgcopy_message(new_message)

    @commands.Cog.listener('on_message')
    async def on_imgblacklist_message(self, message):
        if message.author.id == self.bot.user.id or isinstance(message.channel, discord.abc.PrivateChannel):
            return
        img_blacklist = self.settings.getImageTypeBlacklist(message.guild.id, message.channel.id)
        if img_blacklist is None:
            return

        if message.attachments:
            for a in message.attachments:
                if self._check_labels_for_blacklist(a.url, img_blacklist):
                    await message.channel.send(inline('Hey, is there a {} in that picture!!!'.format(img_blacklist)))
                    return
            return

        if message.embeds:
            for e in message.embeds:
                if self._check_labels_for_blacklist(e.thumbnail.proxy_url, img_blacklist):
                    await message.channel.send(inline('Hey, is there a {} in that picture!!!'.format(img_blacklist)))
                    return
            return

    @commands.Cog.listener('on_message_edit')
    async def on_imgblacklist_edit_message(self, old_message, new_message):
        if len(old_message.embeds) == 0 and len(new_message.embeds) > 0:
            await self.on_imgblacklist_message(new_message)

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def bulkimagecopy(self, ctx, source_channel: discord.TextChannel, dest_channel: discord.TextChannel, number: int):
        copy_items = []
        async for message in source_channel.history(limit=number):
            if message.author.id == self.bot.user.id or isinstance(message.channel, discord.abc.PrivateChannel):
                continue
            img_url = extract_image_url(message)
            if img_url:
                copy_items.append((img_url, message.author.name,
                                   message.channel.name, dest_channel.id))

        copy_items.reverse()
        for item in copy_items:
            try:
                await self.copy_image_to_channel(item[0], item[1], item[2], item[3])
            except Exception as error:
                print(error)

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def imagetypeblacklist(self, ctx, channel: discord.TextChannel, image_type: str):
        self.settings.setImageTypeBlacklist(ctx.guild.id, channel.id, image_type)
        await ctx.send('`done`')

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def clearimagetypeblacklist(self, ctx, channel: discord.TextChannel, image_type: str):
        self.settings.clearImageTypeBlacklist(ctx.guild.id, channel.id)
        await ctx.send('`done`')

    @commands.command()
    @checks.is_owner()
    async def loadallcogs(self, ctx):
        # TODO: Test this when done!
        cogs = ['RpadUtils', 'AutoMod2', 'ChannelMod', 'Donations', 'FancySay', 'Memes',
                'PadBoard', 'Profile', 'Stickers', 'StreamCopy', 'Translate', 'VoiceRole',
                'Dadguide', 'PadEvents', 'PadGlobal', 'PadInfo', 'PadRem']

        owner_cog = self.bot.get_cog('Owner')

        for cog_name in cogs:
            cog = self.bot.get_cog(cog_name)
            if cog is None:
                await ctx.send('{} not loaded, trying to load it...'.format(cog_name))
                try:
                    module = 'cogs.{}'.format(cog_name.lower())
                    owner_cog._load_cog(module)
                    self.bot.add_cog(module)
                except Exception as e:
                    await ctx.send(box("Loading cog failed: {}: {}".format(e.__class__.__name__, str(e))))
        await ctx.send('Done!')

    @commands.command()
    async def getmiru(self, ctx):
        """Tells you how to get Miru into your server"""
        for page in pagify(GETMIRU_HELP, delims=['\n'], shorten_by=8):
            await ctx.author.send(box(page))

    @commands.command()
    async def userhelp(self, ctx):
        """Shows a summary of the useful user features"""
        for page in pagify(USER_HELP, delims=['\n'], shorten_by=8):
            await ctx.author.send(box(page))

    @commands.command()
    @checks.mod_or_permissions(manage_guild=True)
    async def modhelp(self, ctx):
        """Shows a summary of the useful moderator features"""
        for page in pagify(MOD_HELP, delims=['\n'], shorten_by=8):
            await ctx.author.send(box(page))

    @commands.command()
    async def credits(self, ctx):
        """Shows info about this bot"""
        author_repo = "https://github.com/Twentysix26"
        red_repo = author_repo + "/Red-DiscordBot"
        rpad_invite = "https://discord.gg/pad"

        about = (
            "This is an instance of [the Red Discord bot]({}), "
            "use the 'info' command for more info. "
            "The various PAD related cogs were created by tactical_retreat. "
            "This bot was created for the [PAD Community Server Discord]({}) but "
            "is available for other servers on request."
            "".format(red_repo, rpad_invite))

        baby_miru_url = "http://www.pixiv.net/member_illust.php?illust_id=57613867&mode=medium"
        baby_miru_author = "BOW @ Pixiv"
        cute_miru_url = "https://www.dropbox.com/s/0wlfx3g4mk8c8bg/Screenshot%202016-12-03%2018.39.37.png?dl=0"
        cute_miru_author = "Pancaaake18 on discord"
        bot_miru_url = "https://puu.sh/urTm8/c3bdf993bd.png"
        bot_miru_author = "graps on discord"
        avatar = (
            "Bot avatars supplied by:\n"
            "\t[Baby Miru]({}): {}\n"
            "\t[Cute Miru]({}): {}\n"
            "\t[Bot Miru]({}): {}"
            "".format(baby_miru_url, baby_miru_author,
                      cute_miru_url, cute_miru_author,
                      bot_miru_url, bot_miru_author))

        using = (
            "You can use `^help` to get a full list of commands.\n"
            "Use `^userhelp` to get a summary of useful user features.\n"
            "Use `^modhelp` to get info on moderator-only features."
        )

        embed = discord.Embed()
        embed.add_field(name="Instance owned by", value='tactical_retreat')
        embed.add_field(name="About the bot", value=about, inline=False)
        embed.add_field(name="Using the bot", value=using, inline=False)
        embed.add_field(name="Avatar credits", value=avatar, inline=False)
        embed.set_thumbnail(url=self.bot.user.avatar_url)

        try:
            await ctx.send(embed=embed)
        except discord.HTTPException:
            await ctx.send("I need the `Embed links` permission to send this")

    @commands.command(hidden=True)
    @checks.is_owner()
    async def supersecretdebug(self, ctx, *, code):
        await self._superdebug(ctx, code=code)
        await ctx.message.delete()

    @commands.command(hidden=True)
    @checks.is_owner()
    async def superdebug(self, ctx, *, code):
        """Evaluates code"""
        await self._superdebug(ctx, code=code)

    async def _superdebug(self, ctx, *, code):
        def check(m):
            if m.content.strip().lower() == "more":
                return True

        author = ctx.author
        channel = ctx.channel

        code = code.strip('` ')
        result = None

        global_vars = globals().copy()
        global_vars['bot'] = self.bot
        global_vars['ctx'] = ctx
        global_vars['message'] = ctx.message
        global_vars['author'] = ctx.author
        global_vars['channel'] = ctx.channel
        global_vars['guild'] = ctx.guild

        local_vars = locals().copy()
        local_vars['to_await'] = list()

        try:
            eval(compile(code, '<string>', 'exec'), global_vars, local_vars)
            to_await = local_vars['to_await']
        except Exception as e:
            await ctx.send(box('{}: {}'.format(type(e).__name__, str(e)),
                                lang="py"))
            return

        for result in to_await:
            if asyncio.iscoroutine(result):
                result = await result

    @commands.command()
    @checks.is_owner()
    async def checkimg(self, ctx, img: str):
        """Classify the given image and display the results."""
        if img.startswith('https://cdn.discordapp'):
            await ctx.send(inline('That URL probably wont work because Discord blocks non-browser requests'))

        labels = self._get_image_labels(img)
        if labels is None:
            await ctx.send(inline('failed to classify, check your URL'))
            return

        if len(labels):
            formatted_labels = map(lambda l: '({} {:.0%})'.format(l.description, l.score), labels)
            await ctx.send(inline('looks like: ' + ' '.join(formatted_labels)))
        else:
            await ctx.send(inline('not sure what that is'))

    def _get_image_labels(self, img: str):
        # TODO: Fix this.  I don't have a google API
        client = vision.ImageAnnotatorClient()#project='rpad-discord')
        image = vision.types.Image()
        image.source.image_uri = img

        try:
            return client.label_detection(image=image).label_annotations
        except Exception as e:
            print(str(e))
            return None

    def _check_labels_for_blacklist(self, img: str, blacklist: str):
        blacklist = blacklist.lower()
        labels = self._get_image_labels(img)
        if labels is None:
            return False
        for l in labels:
            if blacklist in l.description.lower():
                return True
        return False

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def addroleall(self, ctx, rolename: str):
        """Ensures that everyone in the server has a role."""
        role = get_role(ctx.guild.roles, rolename)
        guild = ctx.guild
        members = guild.members

        def ignore_role_fn(m: discord.Member):
            return role in m.roles

        async def change_role_fn(m: discord.Member):
            await m.add_roles(role)

        await ctx.send(inline("About to ensure that all {} members in the server have role: {}".format(len(members), role.name)))
        await self._do_all_members(ctx, members, ignore_role_fn, change_role_fn)
        await ctx.send("done")

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def rmroleall(self, ctx, rolename: str):
        """Ensures that everyone in the server does not have a role."""
        role = get_role(ctx.guild.roles, rolename)
        guild = ctx.guild
        members = guild.members

        def ignore_role_fn(m: discord.Member):
            return role not in m.roles

        async def change_role_fn(m: discord.Member):
            await m.remove_roles(role)

        await ctx.send(inline("About to ensure that all {} members in the server do not have role: {}".format(len(members), role.name)))
        await self._do_all_members(ctx, members, ignore_role_fn, change_role_fn)
        await ctx.send("done")

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def addroleallrole(self, ctx, srcrolename: str, newrolename: str):
        """Ensures that everyone in the with srcrolename server has a newrolename."""
        srcrole = get_role(ctx.guild.roles, srcrolename)
        newrole = get_role(ctx.guild.roles, newrolename)
        guild = ctx.guild
        members = guild.members

        def ignore_role_fn(m: discord.Member):
            return srcrole not in m.roles or newrole in m.roles

        async def change_role_fn(m: discord.Member):
            await m.add_roles(newrole)

        await ctx.send(inline("About to ensure that all members in the server with role {} have role: {}".format(srcrole.name, newrole.name)))
        await self._do_all_members(ctx, members, ignore_role_fn, change_role_fn)
        await ctx.send("done")

    async def _do_all_members(self, ctx, members, ignore_role_fn, per_member_asyncfn):
        changed, ignored, errors = 0, 0, 0
        for m in members:
            if ignore_role_fn(m):
                ignored += 1
            else:
                try:
                    await per_member_asyncfn(m)
                    await asyncio.sleep(1)
                    changed += 1
                except:
                    errors += 1
            if (changed + ignored + errors) % 10 == 0:
                await ctx.send(inline('Status: changed={} ignored={} errors={}'.format(changed, ignored, errors)))

    @commands.command()
    @checks.is_owner()
    async def superfuckingban(self, ctx, user: discord.User, *, reason: str):
        """Really fucking bans someone.

        This will ban a user from every guild that the bot can ban them from. Use with caution.
        """
        msg = 'Ban report for {} ({}):'.format(user.name, user.id)
        for guild in self.bot.guilds:
            try:
                ban_list = await guild.bans()
                if user.id in [x.user.id for x in ban_list]:
                    msg += '\n\tUser already banned from {}'.format(guild.name)
                    continue
            except:
                msg += '\n\tNot allowed to ban in {}; nothing I can do here'.format(guild.name)
                continue

            m = guild.get_member(user.id)
            if m is None:
                try:
                    await self.bot.http.ban(user.id, guild.id, 0)
                    msg += '\n\tUser not in {}; added to hackban'.format(guild.name)
                    await modlog.create_case(bot = self.bot,
                                             guild = guild,
                                             created_at = datetime.datetime.now(),
                                             action_type="hackban",
                                             moderator=ctx.author,
                                             user=user,
                                             reason='SuperBan by bot owner: {}'.format(reason))
                except Exception as ex:
                    msg += '\n\tUser not in {}; hackban failed: {}'.format(guild.name, ex)
                continue
            try:
                await m.ban(delete_message_days=0)
                msg += '\n\tBanned from {}'.format(guild.name)
                await modlog.create_case(bot = self.bot,
                                         guild = guild,
                                         created_at = datetime.datetime.now(),
                                         action_type="ban",
                                         moderator=ctx.author,
                                         user=user,
                                         reason='SuperBan by bot owner: {}'.format(reason))
            except Exception as ex:
                msg += '\n\tFailed to ban from {} because {}'.format(guild.name, ex)

        for page in pagify(msg):
            await ctx.send(box(page))

    async def _send_feedback(self, ctx, message: str, feedback_channel, success_message: str):
        if feedback_channel is None:
            raise ReportableError("Feedback channel not set")

        guild = ctx.guild
        author = ctx.author
        footer = "User ID: " + str(author.id)

        if guild:
            source = "from {}".format(guild)
            footer += " | Guild ID: " + str(guild.id)
        else:
            source = "through DM"

        description = "Sent by {} {}".format(author, source)

        e = discord.Embed(description=message)
        if author.avatar_url:
            e.set_author(name=description, icon_url=author.avatar_url)
        else:
            e.set_author(name=description)
        e.set_footer(text=footer)

        try:
            await feedback_channel.send(embed=e)
        except:
            await ctx.send(inline("I'm unable to deliver your message. Sorry."))
        else:
            await ctx.send(inline("Your message has been sent."
                                      " Abusing this feature will result in a blacklist."
                                      + success_message))

    @commands.command()
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def feedback(self, ctx, *, message: str):
        """Provide feedback on the bot.

        Use this command to provide feedback on the bot, including new features, changes
        to commands, requests for new ^pad/^which entries, etc.
        """
        feedback_channel = self.bot.get_channel(int(self.settings.getFeedbackChannel()))
        await self._send_feedback(ctx, message, feedback_channel, " Join the Miru Server to see any responses (^miruserver).")

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def setfeedbackchannel(self, ctx, channel: discord.TextChannel):
        """Set the feedback destination channel."""
        self.settings.setFeedbackChannel(channel.id)
        await ctx.send(inline('Done'))

    @commands.command(aliases=['mamafeedback'])
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def blogfeedback(self, ctx, *, message: str):
        """Provide feedback on Reni's blog or translations.

        Use this command to submit feedback on https://pad.protic.site or the JP translations.
        """
        feedback_channel = self.bot.get_channel(int(self.settings.getBlogFeedbackChannel()))
        await self._send_feedback(ctx, message, feedback_channel, " Join the PDX Server to see any responses (^pdx).")

    @commands.command()
    @commands.guild_only()
    @checks.is_owner()
    async def setblogfeedbackchannel(self, ctx, channel: discord.TextChannel):
        """Set the blog feedback destination channel."""
        self.settings.setBlogFeedbackChannel(channel.id)
        await ctx.send(inline('Done'))

    @commands.command()
    @commands.guild_only()
    @checks.mod_or_permissions(manage_guild=True)
    async def mentionable(self, ctx, role: discord.Role):
        """Toggle the mentionability of a role."""
        try:
            new_mentionable = not role.mentionable
            await role.edit(mentionable=new_mentionable)
            await ctx.send(inline('Role is now {}'.format('mentionable' if new_mentionable else 'unmentionable')))
        except Exception as ex:
            await ctx.send(inline('Error: failed to alter role'))

    @commands.command()
    @checks.is_owner()
    async def trackuser(self, ctx, user: discord.User=None):
        """Track/untrack a user, list track info."""
        if user:
            if user.id in self.settings.trackedUsers().keys():
                self.settings.rmTrackedUser(user.id)
                await ctx.send(inline('No longer tracking user'))
            else:
                self.settings.addTrackedUser(user.id)
                await ctx.send(inline('Tracking user'))
                for guild in self.bot.guilds:
                    member = guild.get_member(user.id)
                    if member and str(member.status) != 'offline':
                        self.settings.updateTrackedUser(user.id)
                        await ctx.send(inline('User currently online'))
                        break
        else:
            msg = 'Tracked users:\n'
            for user_id, track_info in self.settings.trackedUsers().items():
                user = await self.bot.fetch_user(user_id)
                user_name = user.name if user else user_id
                msg += '\t{} : {}'.format(user_name, json.dumps(track_info))

            await ctx.send(box(msg))

    @commands.Cog.listener('on_member_update')
    async def on_trackuser_update(self, old_member: discord.Member, new_member: discord.Member):
        if new_member and str(new_member.status) != 'offline' and new_member.id in self.settings.trackedUsers():
            self.settings.updateTrackedUser(new_member.id)


class TrUtilsSettings(CogSettings):
    def make_default_settings(self):
        config = {
            'servers': {},
            'tracked_users': {},
        }
        return config

    def servers(self):
        return self.bot_settings['servers']

    def getServer(self, server_id):
        servers = self.servers()
        if server_id not in servers:
            servers[server_id] = {}
        return servers[server_id]

    def imagecopy(self, server_id):
        server = self.getServer(server_id)
        if 'imgcopy' not in server:
            server['imgcopy'] = {}
        return server['imgcopy']

    def setImageCopy(self, server_id, source_channel_id, dest_channel_id):
        imagecopy = self.imagecopy(server_id)
        imagecopy[source_channel_id] = dest_channel_id
        self.save_settings()

    def getImageCopy(self, server_id, channel_id):
        imagecopy = self.imagecopy(server_id)
        return imagecopy.get(channel_id)

    def clearImageCopy(self, server_id, channel_id):
        imagecopy = self.imagecopy(server_id)
        if channel_id in imagecopy:
            imagecopy.pop(channel_id)
            self.save_settings()

    def imagetypeblacklist(self, server_id):
        key = 'imgtypeblacklist'
        server = self.getServer(server_id)
        if key not in server:
            server[key] = {}
        return server[key]

    def setImageTypeBlacklist(self, server_id, channel_id, image_type):
        imagebl = self.imagetypeblacklist(server_id)
        imagebl[channel_id] = image_type
        self.save_settings()

    def getImageTypeBlacklist(self, server_id, channel_id):
        imagebl = self.imagetypeblacklist(server_id)
        return imagebl.get(channel_id)

    def clearImageTypeBlacklist(self, server_id, channel_id):
        imagebl = self.imagetypeblacklist(server_id)
        if channel_id in imagebl:
            imagebl.pop(channel_id)
            self.save_settings()

    def getFeedbackChannel(self):
        return self.bot_settings.get('feedback_channel')

    def setFeedbackChannel(self, channel_id: int):
        self.bot_settings['feedback_channel'] = str(channel_id)
        self.save_settings()

    def getBlogFeedbackChannel(self):
        return self.bot_settings.get('blog_feedback_channel')

    def setBlogFeedbackChannel(self, channel_id: int):
        self.bot_settings['blog_feedback_channel'] = str(channel_id)
        self.save_settings()

    def curtimestr(self):
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    def trackedUsers(self):
        return self.bot_settings['tracked_users']

    def addTrackedUser(self, user_id):
        self.trackedUsers()[user_id] = {'last_seen': 'never', 'tracked_on': self.curtimestr()}
        self.save_settings()

    def updateTrackedUser(self, user_id):
        self.trackedUsers()[user_id]['last_seen'] = self.curtimestr()
        self.save_settings()

    def rmTrackedUser(self, user_id):
        self.trackedUsers().pop(user_id)
        self.save_settings()

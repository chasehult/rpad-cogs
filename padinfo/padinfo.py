import asyncio
from builtins import filter
from collections import OrderedDict, Counter
from collections import defaultdict
import csv
from datetime import datetime
from datetime import timedelta
from enum import Enum
import http.client
from itertools import groupby
import json
from operator import itemgetter
import os
import re
import threading
import time
import time
import traceback
import urllib.parse

from dateutil import tz
import discord
from discord.ext import commands
import prettytable
import pytz
import romkan
from setuptools.command.alias import alias

from __main__ import user_allowed, send_cmd_help

from . import padguide
from .rpadutils import *
from .utils import checks
from .utils.chat_formatting import *
from .utils.cog_settings import *
from .utils.dataIO import fileIO
from .utils.padguide import *
from .utils.twitter_stream import *


# from copy import deepcopy
class OrderedCounter(Counter, OrderedDict):
    """Counter that remembers the order elements are first seen"""
    def __repr__(self):
        return "%s(%r)" % (self.__class_.__name__, OrderedDict(self))

    def __reduce__(self):
        return self.__class__, (OrderedDict(self),)


EXPOSED_PAD_INFO = None

class PadInfo:
    def __init__(self, bot):
        self.bot = bot

        self.settings = PadInfoSettings("padinfo")

        self.nickname_text = dl_nicknames()
        self.pginfo = PgDataWrapper()
        self.pginfo.populateWithOverrides(self.nickname_text)

        self.id_to_monster = self.pginfo.id_to_monster

        global EXPOSED_PAD_INFO
        EXPOSED_PAD_INFO = self


    def __unload(self):
        print("unloading padinfo")
        self.reload_nicknames_task.cancel()

        global EXPOSED_PAD_INFO
        EXPOSED_PAD_INFO = None

    def registerTasks(self, event_loop):
        print("registering tasks")
        self.reload_nicknames_task = event_loop.create_task(self.reload_nicknames())

    async def reload_nicknames(self):
        print("nickname reloader")
        first_run = True
        while "PadInfo" in self.bot.cogs:
            do_short = False
            try:
                if not first_run:
                    self.download_and_refresh_nicknames()
                first_run = False
            except Exception as e:
                traceback.print_exc()
                do_short = True
                print("caught exception while loading nicknames " + str(e))

            try:
                if do_short:
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(60 * 60 * 4)
            except Exception as e:
                print('wut')
                traceback.print_exc()
                print("reload nickname loop caught exception " + str(e))
                raise e

        print("done reload_nicknames")

    def download_and_refresh_nicknames(self):
        self.nickname_text = dl_nicknames()
        self.pginfo = PgDataWrapper()
        self.pginfo.populateWithOverrides(self.nickname_text)

#         self.pgrem = PgRemWrapper()
#         self.pgrem.populateWithMonsters(self.pginfo.full_monster_map)

        self.id_to_monster = self.pginfo.id_to_monster

    async def on_ready(self):
        """ready"""
        print("started padinfo")

    @commands.command(name="id", pass_context=True)
    async def _doid(self, ctx, *query):
        query = " ".join(query)
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            embed = monsterToEmbed(m, ctx.message.server)
            try:
                await self.bot.say(embed=embed)
            except Exception as e:
                info, link = monsterToInfoText(m)
                await self.bot.say(box(info) + '\n<' + link + '>')
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="idz", pass_context=True)
    async def _doidz(self, ctx, *query):
        query = " ".join(query)
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            info, link = monsterToInfoText(m)
            await self.bot.say(box(info) + '\n<' + link + '>')
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="debugid", pass_context=True)
    @checks.mod_or_permissions(manage_server=True)
    async def _dodebugid(self, ctx, *query):
        query = " ".join(query)

        m, err, debug_info = self.findMonster(query)
        if m is not None:
            info, link = monsterToInfoText(m)
            await self.bot.say(box(info))
            await self.bot.say(box('Lookup type: ' + debug_info + '\nMonster info: ' + m.debug_info))
        else:
            await self.bot.say(self.makeFailureMsg(err))

    @commands.command(name="pic", pass_context=True, aliases=['img'])
    async def _dopic(self, ctx, *query):
        query = " ".join(query)
        m, err, debug_info = self.findMonster(query)
        if m is not None:
            header, link = monsterToPicText(m)
            await self.bot.say(inline(header) + '\n' + link)
        else:
            await self.bot.say(self.makeFailureMsg(err))


    @commands.command(name="helpid", pass_context=True, aliases=['helppic', 'helpimg'])
    async def _helpid(self, ctx):
        helpMsg = "^helpid : shows this message"
        helpMsg += "\n" + "^id <query> : look up a monster and print a link to puzzledragonx"
        helpMsg += "\n" + "^pic <query> : Look up a monster and display its image inline"
        helpMsg += "\n\n" + "Options for <query>"
        helpMsg += "\n\t" + "<id> : Find a monster by ID"
        helpMsg += "\n\t\t" + "^id 1234 (picks sun quan)"
        helpMsg += "\n\t" + "<name> : Take the best guess for a monster, picks the most recent monster"
        helpMsg += "\n\t\t" + "^id kali (picks uvo d kali)"
        helpMsg += "\n\t" + "<prefix> <name> : Limit by element or awoken, e.g."
        helpMsg += "\n\t\t" + "^id ares  (selects the most recent, awoken ares)"
        helpMsg += "\n\t\t" + "^id aares (explicitly selects awoken ares)"
        helpMsg += "\n\t\t" + "^id a ares (spaces work too)"
        helpMsg += "\n\t\t" + "^id rd ares (select a specific evo for ares, the red/dark one)"
        helpMsg += "\n\t\t" + "^id r/d ares (slashes, spaces work too)"
        helpMsg += "\n\n" + "computed nickname list and overrides: https://docs.google.com/spreadsheets/d/1EyzMjvf8ZCQ4K-gJYnNkiZlCEsT9YYI9dUd-T5qCirc/pubhtml"
        helpMsg += "\n\n" + "submit an override suggestion: https://docs.google.com/forms/d/1kJH9Q0S8iqqULwrRqB9dSxMOMebZj6uZjECqi4t9_z0/edit"
        await self.bot.whisper(box(helpMsg))

    def makeFailureMsg(self, err):
        msg = 'Lookup failed: ' + err + '.\n'
        msg += 'Try one of <id>, <name>, [argbld]/[rgbld] <name>. Unexpected results? Use ^helpid for more info.'
        return box(msg)

    def findMonster(self, query):
        query = query.lower().strip()

        # id search
        if query.isdigit():
            m = self.id_to_monster.get(int(query))
            if m is None:
                return None, 'Looks like a monster ID but was not found', None
            else:
                return m, None, "ID lookup"
            # special handling for na/jp

        # handle exact nickname match
        if query in self.pginfo.all_entries:
            return self.pginfo.all_entries[query], None, "Exact nickname"

        if len(query) < 4:
            return None, 'Your query must be at least 4 letters', None

        matches = list()
        # prefix search for nicknames, space-preceeded, take max id
        for nickname, m in self.pginfo.all_entries.items():
            if nickname.startswith(query + ' '):
                matches.append(m)
        if len(matches):
            return pickBestMonster(matches), None, "Space nickname prefix, max of {}".format(len(matches))

        # prefix search for nicknames, take max id
        for nickname, m in self.pginfo.all_entries.items():
            if nickname.startswith(query):
                matches.append(m)
        if len(matches):
            all_names = ",".join(map(lambda x: x.name_na, matches))
            return pickBestMonster(matches), None, "Nickname prefix, max of {}, matches=({})".format(len(matches), all_names)

        # prefix search for full name, take max id
        for nickname, m in self.pginfo.all_entries.items():
            if m.name_na.lower().startswith(query) or m.name_jp.lower().startswith(query):
                matches.append(m)
        if len(matches):
            return pickBestMonster(matches), None, "Full name, max of {}".format(len(matches))


        # for nicknames with 2 names, prefix search 2nd word, take max id
        if query in self.pginfo.two_word_entries:
            return self.pginfo.two_word_entries[query], None, "Second-word nickname prefix, max of {}".format(len(matches))

        # TODO: refactor 2nd search characteristcs for 2nd word

        # full name contains on nickname, take max id
        for nickname, m in self.pginfo.all_entries.items():
            if query in m.name_na.lower() or query in m.name_jp.lower():
                matches.append(m)
        if len(matches):
            return pickBestMonster(matches), None, 'Full name match on nickname, max of {}'.format(len(matches))

        # full name contains on full monster list, take max id

        for m in self.pginfo.full_monster_list:
            if query in m.name_na.lower() or query in m.name_jp.lower():
                matches.append(m)
        if len(matches):
            return pickBestMonster(matches), None, 'Full name match on full list, max of {}'.format(len(matches))

        # couldn't find anything
        return None, "Could not find a match for: " + query, None

def pickBestMonster(monster_list):
    return max(monster_list, key=lambda x: (x.selection_priority, x.rarity, x.monster_id_na))


def setup(bot):
    print('padinfo bot setup')
    n = PadInfo(bot)
    n.registerTasks(asyncio.get_event_loop())
    bot.add_cog(n)
    print('done adding padinfo bot')


class PadInfoSettings(CogSettings):
    def make_default_settings(self):
        config = {}
        return config



HIGH_SELECTION_PRIORITY = 2
LOW_SELECTION_PRIORITY = 1
UNKNOWN_SELECTION_PRIORITY = 0

class Monster:
    def __init__(self,
                 base_monster,
                 monster_info,
                 additional_info,
                 awakening_skills,
                 evos,
                 active_skill,
                 leader_skill,
                 type_map,
                 attribute_map):

        self.monster_id = base_monster.monster_id
        # NA is used in puzzledragonx
        self.monster_id_na = base_monster.monster_id_na
        self.monster_id_jp = base_monster.monster_id_jp

        self.debug_info = ''
        self.selection_priority = UNKNOWN_SELECTION_PRIORITY

        self.evo_to = [x.to_monster_id for x in evos]
        self.evo_from = list()

        self.awakening_names = [x.name for x in awakening_skills]

        self.hp = int(base_monster.hp)
        self.atk = int(base_monster.atk)
        self.rcv = int(base_monster.rcv)
        self.weighted_stats = int(self.hp / 10 + self.atk / 5 + self.rcv / 3)

        self.rarity = int(base_monster.rarity)
        self.cost = int(base_monster.cost)
        self.max_level = int(base_monster.max_level)

        self.name_na = base_monster.name_na
        self.name_jp = base_monster.name_jp

        self.on_us = monster_info.on_us == '1'
        self.on_na = monster_info.on_us == '1'
        self.series_id = monster_info.series_id
        self.is_gfe = self.series_id == '34'

        self.roma_subname = None
        if self.name_jp == self.name_na and ('・' in self.name_jp or '＝' in self.name_jp):
            subname = self.name_jp.replace('＝', '')
            adjusted_subname = ''
            for part in subname.split('・'):
                roma_part = romkan.to_roma(part)
                if part != roma_part and not containsJp(roma_part):
                    adjusted_subname += ' ' + roma_part.strip('-')
            adjusted_subname = adjusted_subname.strip()
            if adjusted_subname:
                self.roma_subname = adjusted_subname
                self.debug_info += '| roma: ' + adjusted_subname

        self.attr1 = None
        self.attr2 = None
        if base_monster.attr1 != '0':
            self.attr1 = attribute_map[base_monster.attr1].name
        if base_monster.attr2 != '0':
            self.attr2 = attribute_map[base_monster.attr2].name

        self.type1 = None
        self.type2 = None
        self.type3 = None
        if base_monster.type1 != '0':
            self.type1 = type_map[base_monster.type1].name
        if base_monster.type2 != '0':
            self.type2 = type_map[base_monster.type2].name
        if additional_info and additional_info.sub_type != '0':
            self.type3 = type_map[additional_info.sub_type].name

        self.active_text = None
        if active_skill:
            self.active_text = active_skill.desc
            self.active_min = active_skill.turn_min
            self.active_max = active_skill.turn_max

        self.leader_text = None
        if leader_skill:
            self.leader_text = leader_skill.desc

def monsterToInfoText(m: Monster):
    header = 'No. {} {}'.format(m.monster_id_na, m.name_na)

    if m.roma_subname:
        header += ' [{}]'.format(m.roma_subname)

    if not m.on_us:
        header += ' (JP only)'

    info_row = m.attr1
    if m.attr2:
        info_row += '/' + m.attr2

    info_row += '  |  ' + m.type1
    if m.type2:
        info_row += '/' + m.type2
    if m.type3:
        info_row += '/' + m.type3

    info_row += '  |  Rarity:' + str(m.rarity)
    info_row += '  |  Cost:' + str(m.cost)

    stats_row = 'Lv. {}  HP {}  ATK {}  RCV {}  Weighted {}'.format(m.max_level, m.hp, m.atk, m.rcv, m.weighted_stats)

    awakenings_row = ''
    unique_awakenings = set(m.awakening_names)
    for a in unique_awakenings:
        count = m.awakening_names.count(a)
        awakenings_row += ' {}x{}'.format(AWAKENING_NAME_MAP.get(a, a), count)
    awakenings_row = awakenings_row.strip()

    if not len(awakenings_row):
        awakenings_row = 'No Awakenings'

    ls_row = 'LS: '
    if m.leader_text:
        ls_row += m.leader_text
    else:
        ls_row += 'None/Missing'

    active_row = 'AS: '
    if m.active_text:
        active_row += '({}->{}): {}'.format(m.active_max, m.active_min, m.active_text)
    else:
        active_row += 'None/Missing'

    info_chunk = '{}\n{}\n{}\n{}\n{}\n{}'.format(header, info_row, stats_row, awakenings_row, ls_row, active_row)
    link_row = 'http://www.puzzledragonx.com/en/monster.asp?n={}'.format(m.monster_id_na)

    return info_chunk, link_row

def monsterToPicText(m: Monster):
    header = 'No. {} {}'.format(m.monster_id_na, m.name_na)
    link = 'http://www.puzzledragonx.com/en/img/monster/MONS_{}.jpg'.format(m.monster_id_na)
    return header, link

def monsterToEmbed(m: Monster, server):
    header = 'No. {} {}'.format(m.monster_id_na, m.name_na)

    if m.roma_subname:
        header += ' [{}]'.format(m.roma_subname)

    if not m.on_us:
        header += ' (JP only)'

    embed = discord.Embed()
    embed.set_thumbnail(url='http://www.puzzledragonx.com/en/img/book/{}.png'.format(m.monster_id_na))
    embed.title = header
    embed.description = 'this is a description'
    embed.url = 'http://www.puzzledragonx.com/en/monster.asp?n={}'.format(m.monster_id_na)

    info_row_1 = m.type1
    if m.type2:
        info_row_1 += '/' + m.type2
    if m.type3:
        info_row_1 += '/' + m.type3

    info_row_2 = '**Rarity** {}\n**Cost** {}'.format(m.rarity, m.cost)
    embed.add_field(name=info_row_1, value=info_row_2)

    stats_row_1 = 'Weighted {}'.format(m.weighted_stats)
    stats_row_2 = '**HP** {}\n**ATK** {}\n**RCV** {}'.format(m.hp, m.atk, m.rcv)
    embed.add_field(name=stats_row_1, value=stats_row_2)

    awakenings_row = ''
    unique_awakenings = OrderedCounter(m.awakening_names)
    for a, count in unique_awakenings.items():
        mapped_awakening = AWAKENING_NAME_MAP_RPAD.get(a) if server is not None else None
        if mapped_awakening:
            mapped_awakening = discord.utils.get(server.emojis, name=mapped_awakening)

        if mapped_awakening is None:
            mapped_awakening = AWAKENING_NAME_MAP.get(a, a)
            awakenings_row += ' {}x{}'.format(mapped_awakening, count)
        else:
            awakenings_row += (' ' + str(mapped_awakening)) * count



    awakenings_row = awakenings_row.strip()

    if not len(awakenings_row):
        awakenings_row = 'No Awakenings'

    embed.description = awakenings_row

    active_header = 'Active Skill'
    active_body = 'None/Missing'
    if m.active_text:
        active_header = 'Active Skill ({} -> {})'.format(m.active_max, m.active_min, m.active_text)
        active_body = m.active_text
    embed.add_field(name=active_header, value=active_body, inline=False)

    ls_row = m.leader_text if m.leader_text else 'None/Missing'
    embed.add_field(name='Leader Skill', value=ls_row, inline=False)


    return embed

attr_prefix_map = {
  'Fire':'r',
  'Water':'b',
  'Wood':'g',
  'Light':'l',
  'Dark':'d',
}

attr_prefix_long_map = {
  'Fire':'red',
  'Water':'blue',
  'Wood':'green',
  'Light':'light',
  'Dark':'dark',
}

series_to_prefix_map = {
  '130' : ['halloween'],
  '136' : ['xmas', 'christmas'],
  '125' : ['summer', 'beach'],
  '114' : ['school'],
  '139' : ['new years', 'ny'],
  '149' : ['wedding', 'bride'],
  '154' : ['padr'],
}

AWAKENING_NAME_MAP_RPAD = {
  'Enhanced Fire Orbs': 'oe6fire',
  'Enhanced Water Orbs': 'oe5water',
  'Enhanced Wood Orbs': 'oe4wood',
  'Enhanced Light Orbs': 'oe3light',
  'Enhanced Dark Orbs': 'oe2dark',
  'Enhanced Heal Orbs': 'oe1heart',

  'Enhanced Fire Att.': 'row6fire',
  'Enhanced Water Att.': 'row5water',
  'Enhanced Wood Att.': 'row4wood',
  'Enhanced Light Att.': 'row3light',
  'Enhanced Dark Att.': 'row2dark',

  'Enhanced HP': 'boost_hp',
  'Enhanced Attack': 'boost_atk',
  'Enhanced Heal': 'boost_rcv',

  'Auto-Recover': 'awakening_autoheal',
  'Skill Boost': 'awakening_sb',
  'Resistance-Skill Bind': 'awakening_sbr',
  'Two-Pronged Attack': 'awakening_tpa',
  'Multi Boost': 'awakening_multiboost',
  'Recover Bind': 'row1bindclear',
  'Extend Time': 'awakening_te',

  'Resistance-Bind': 'awakening_bindres',
  'Resistance-Dark': 'awakening_blindres',
  'Resistance-Poison': 'awakening_poisonres',
  'Resistance-Jammers': 'awakening_jammerres',

  'Reduce Fire Damage': 'reduce_fire',
  'Reduce Water Damage': 'reduce_water',
  'Reduce Wood Damage': 'reduce_wood',
  'Reduce Light Damage': 'reduce_light',
  'Reduce Dark Damage': 'reduce_dark',

  'Healer Killer': 'killerhealer',
  'Machine Killer': 'killermachine',
  'Dragon Killer': 'killerdragon',
  'Attacker Killer': 'killerattacker',
  'Physical Killer': 'killerphysical',
  'God Killer': 'killergod',
  'Devil Killer': 'killerdevil',
  'Balance Killer': 'killerbalance',

  'Awoken Killer': 'killerawoken',
  'Evolve Material Killer': 'killerevomat',
  'Enhance Killer': 'killerenhancemat',
  'Vendor Killer': 'killervendor',
}

AWAKENING_NAME_MAP = {
  'Enhanced Fire Orbs': 'R-OE',
  'Enhanced Water Orbs': 'B-OE',
  'Enhanced Wood Orbs': 'G-OE',
  'Enhanced Light Orbs': 'L-OE',
  'Enhanced Dark Orbs': 'D-OE',
  'Enhanced Heal Orbs': 'H-OE',

  'Enhanced Fire Att.': 'R-RE',
  'Enhanced Water Att.': 'B-RE',
  'Enhanced Wood Att.': 'G-RE',
  'Enhanced Light Att.': 'L-RE',
  'Enhanced Dark Att.': 'D-RE',

  'Enhanced HP': 'HP',
  'Enhanced Attack': 'ATK',
  'Enhanced Heal': 'RCV',

  'Auto-Recover': 'AUTO-RECOVER',
  'Skill Boost': 'SB',
  'Resistance-Skill Bind': 'SBR',
  'Two-Pronged Attack': 'TPA',
  'Multi Boost': 'MULTI-BOOST',
  'Recover Bind': 'RCV-BIND',
  'Extend Time': 'TE',

  'Resistance-Bind': 'RES-BIND',
  'Resistance-Dark': 'RES-DARK',
  'Resistance-Poison': 'RES-POISON',
  'Resistance-Jammers': 'RES-JAMMER',

  'Reduce Fire Damage': 'R-RES',
  'Reduce Water Damage': 'B-RES',
  'Reduce Wood Damage': 'G-RES',
  'Reduce Light Damage': 'L-RES',
  'Reduce Dark Damage': 'D-RES',

  'Healer Killer': 'K-HEALER',
  'Machine Killer': 'K-MACHINE',
  'Dragon Killer': 'K-DRAGON',
  'Attacker Killer': 'K-ATTACKER',
  'Physical Killer': 'K-PHYSICAL',
  'God Killer': 'K-GOD',
  'Devil Killer': 'K-DEVIL',
  'Balance Killer': 'K-BALANCE',
}

def addNickname(m: Monster):
    nickname = m.name_na.lower()
    if ',' in nickname:
        name_parts = nickname.split(',')
        if name_parts[1].strip().startswith('the'):
            # handle names like 'xxx, the yyy' where xxx is the name
            nickname = name_parts[0]
        else:
            # otherwise, grab the chunk after the last comma
            nickname = name_parts[-1]

    if 'awoken' in nickname:
        nickname = nickname.replace('awoken', '')

    m.nickname = nickname.strip()

def addPrefixes(m: Monster):
    prefixes = set()

    attr1 = attr_prefix_map[m.attr1]
    prefixes.add(attr1)

    # Add long color names like red/blue
    long_attr = attr_prefix_long_map[m.attr1]
    prefixes.add(long_attr)

    # Add long attr names like fire/water
    prefixes.add(m.attr1.lower())

    if m.attr2 is not None:
        attr2 = attr_prefix_map[m.attr2]
        prefixes.add(attr1 + attr2)
        prefixes.add(attr1 + '/' + attr2)

    # TODO add prefixes based on type

    if m.name_na.lower() == m.name_na and m.name_na != m.name_jp:
        prefixes.add('chibi')

    if 'awoken' in m.name_na.lower() or '覚醒' in m.name_na:
        prefixes.add('a')

    if '覚醒' in m.name_na:
        prefixes.add('awoken')

    if 'reincarnated' in m.name_na.lower() or '転生' in m.name_na:
        prefixes.add('revo')

    if '転生' in m.name_na:
        prefixes.add('reincarnated')

    # Add collab prefixes
    if m.series_id in series_to_prefix_map:
        prefixes.update(series_to_prefix_map[m.series_id])

    m.prefixes = prefixes
    m.debug_info += ' | Prefixes ({})'.format(','.join(prefixes))


class MonsterGroup:
    def __init__(self):
        self.nickname = None
        self.monsters = list()

    def computeNickname(self):
        get_nickname = lambda x: x.nickname
        sorted_monsters = sorted(self.monsters, key=get_nickname)
        grouped = [(c, len(list(cgen))) for c, cgen in groupby(sorted_monsters, get_nickname)]
        best_tuple = max(grouped, key=itemgetter(1))
        self.nickname = best_tuple[0]
        for m in self.monsters:
            m.original_nickname = m.nickname
            m.nickname = self.nickname
            m.debug_info += ' | Original NN ({}) | Final NN ({})'.format(m.original_nickname, m.nickname)
        # might need something here to deal with all uniques, pick the highest


class PgDataWrapper:
    def __init__(self):
        attribute_list = padguide.loadJsonToItem('attributeList.jsp', padguide.PgAttribute)
        awoken_list = padguide.loadJsonToItem('awokenSkillList.jsp', padguide.PgAwakening)
        evolution_list = padguide.loadJsonToItem('evolutionList.jsp', padguide.PgEvo)
        monster_add_info_list = padguide.loadJsonToItem('monsterAddInfoList.jsp', padguide.PgMonsterAddInfo)
        monster_info_list = padguide.loadJsonToItem('monsterInfoList.jsp', padguide.PgMonsterInfo)
        base_monster_list = padguide.loadJsonToItem('monsterList.jsp', padguide.PgBaseMonster)
        skill_list = padguide.loadJsonToItem('skillList.jsp', padguide.PgSkill)
        type_list = padguide.loadJsonToItem('typeList.jsp', padguide.PgType)

        attribute_map = {x.attribute_id: x for x in attribute_list}

        monster_awoken_multimap = defaultdict(list)
        for item in awoken_list:
            monster_awoken_multimap[item.monster_id].append(item)

        monster_evo_multimap = defaultdict(list)
        for item in evolution_list:
            monster_evo_multimap[item.monster_id].append(item)

        monster_add_info_map = {x.monster_id: x for x in monster_add_info_list}
        monster_info_map = {x.monster_id: x for x in monster_info_list}
        skill_map = {x.skill_id: x for x in skill_list}
        type_map = {x.type_id: x for x in type_list}

        self.full_monster_list = list()
        self.full_monster_map = {}
        for base_monster in base_monster_list:
            monster_id = base_monster.monster_id

            awakenings = monster_awoken_multimap[monster_id]
            awakening_skills = [skill_map[x.awakening_id] for x in awakenings]
            evos = monster_evo_multimap[monster_id]
            additional_info = monster_add_info_map.get(monster_id)
            monster_info = monster_info_map[monster_id]
            active_skill = skill_map.get(base_monster.active_id)
            leader_skill = skill_map.get(base_monster.leader_id)

            full_monster = Monster(
                base_monster,
                monster_info,
                additional_info,
                awakening_skills,
                evos,
                active_skill,
                leader_skill,
                type_map,
                attribute_map)

            addNickname(full_monster)
            addPrefixes(full_monster)


            self.full_monster_list.append(full_monster)
            self.full_monster_map[monster_id] = full_monster

        # For each monster, populate the list of monsters that they evo from
        for full_monster in self.full_monster_list:
            for evo_to_id in full_monster.evo_to:
                self.full_monster_map[evo_to_id].evo_from.append(full_monster.monster_id)


        self.hp_monster_groups = list()
        self.lp_monster_groups = list()

        # Create monster groups
        for full_monster in self.full_monster_list:
            # Ignore monsters that can be evo'd to, they're not the base
            if len(full_monster.evo_from):
                full_monster.debug_info += ' | not root'
                continue

            full_monster.debug_info += ' | root'
            # Recursively build the monster group
            mg = MonsterGroup()
            self.buildMonsterGroup(full_monster, mg)

            # Tag the group with the best nickname
            mg.computeNickname()

            # Push the group size into each monster
            for m in mg.monsters:
                m.group_size = len(mg.monsters)
                m.debug_info += ' | grpsize ' + str(len(mg.monsters))

            # Split monster groups into low or high priority ones
            if shouldFilterMonster(mg.monsters[0]) or shouldFilterGroup(mg):
                self.lp_monster_groups.append(mg)
            else:
                self.hp_monster_groups.append(mg)


        # Unzip the monster groups into monster lists
        self.hp_monsters = list()
        self.lp_monsters = list()
        for mg in self.hp_monster_groups:
            for m in mg.monsters:
                self.hp_monsters.append(m)
                m.selection_priority = HIGH_SELECTION_PRIORITY
                m.debug_info += ' | HP'
        for mg in self.lp_monster_groups:
            for m in mg.monsters:
                self.lp_monsters.append(m)
                m.selection_priority = LOW_SELECTION_PRIORITY
                m.debug_info += ' | LP'

        # Sort the monster lists by largest group size first, then largest monster id
        group_id_sort = lambda m: (m.group_size, m.monster_id_na)
        self.hp_monsters.sort(key=group_id_sort, reverse=True)
        self.lp_monsters.sort(key=group_id_sort, reverse=True)

        self.all_entries = {}
        self.two_word_entries = {}

        self.buildNicknameLists(self.hp_monsters)
        self.buildNicknameLists(self.lp_monsters)

        self.id_to_monster = {}
        for m in self.full_monster_list:
            self.id_to_monster[m.monster_id_na] = m

    def maybeAdd(self, name_map, name, monster):
        if name not in name_map:
            name_map[name] = monster

    def buildNicknameLists(self, monster_list):
        for m in monster_list:
            self.maybeAdd(self.all_entries, m.nickname, m)
            for p in m.prefixes:
                self.maybeAdd(self.all_entries, p + m.nickname, m)
                self.maybeAdd(self.all_entries, p + ' ' + m.nickname, m)

            nickname_words = m.nickname.split(' ')
            if len(nickname_words) == 2:
                alt_nickname = nickname_words[1]
                self.maybeAdd(self.two_word_entries, alt_nickname, m)
                for p in m.prefixes:
                    n1 = p + alt_nickname
                    self.maybeAdd(self.two_word_entries, p + alt_nickname, m)
                    self.maybeAdd(self.two_word_entries, p + ' ' + alt_nickname, m)

            if m.roma_subname:
                # print(m.name_jp, 'adding', m.roma_subname)
                self.maybeAdd(self.all_entries, m.roma_subname, m)

    def buildMonsterGroup(self, m: Monster, mg: MonsterGroup):
        mg.monsters.append(m)
        for mto_id in m.evo_to:
            mto = self.full_monster_map[mto_id]
            self.buildMonsterGroup(mto, mg)

    def populateWithOverrides(self, nickname_text):
        nickname_reader = csv.reader(nickname_text.split('\n'), delimiter=',')
        for row in nickname_reader:
            if len(row) < 4:
                continue

            nickname = row[1].strip().lower()
            mId = row[2].strip()
            approved = row[3].strip().upper()

            if not (len(nickname) and len(mId) and len(approved)):
                continue

            if approved != 'TRUE' or not mId.isdigit():
                continue

            monster = self.id_to_monster[int(mId)]
            self.all_entries[nickname] = monster
#             print('adding nickname', mId, nickname, monster.name_na)


def shouldFilterMonster(m: Monster):
    lp_types = ['evolve', 'enhance', 'protected', 'awoken', 'vendor']
    lp_substrings = ['tamadra']
    lp_min_rarity = 2
    name = m.name_na.lower()

    failed_type = m.type1.lower() in lp_types
    failed_ss = any([x in name for x in lp_substrings])
    failed_rarity = m.rarity < lp_min_rarity
    failed_chibi = name == m.name_na

    return failed_type or failed_ss or failed_rarity or failed_chibi

def shouldFilterGroup(mg: MonsterGroup):
    lp_grp_min_rarity = 5
    max_rarity = max(m.rarity for m in mg.monsters)

    failed_max_rarity = max_rarity < lp_grp_min_rarity

    return failed_max_rarity



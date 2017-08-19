"""
Provides access to PadGuide data.

Loads every PadGuide related JSON into a simple data structure, and then
combines them into a an in-memory interconnected database.

Don't hold on to any of the dastructures exported from here, or the
entire database could be leaked when the module is reloaded.
"""
from _collections import defaultdict
import asyncio
import csv
from datetime import datetime
from datetime import timedelta
import difflib
from enum import Enum
from itertools import groupby
from macpath import basename
from operator import itemgetter
import re
import traceback

import discord
from discord.ext import commands
from html5lib.constants import prefixes
from numpy.core.defchararray import lower
import pytz
import romkan
import unidecode

from . import rpadutils
from .utils import checks
from .utils.chat_formatting import box, inline
from .utils.cog_settings import CogSettings
from .utils.dataIO import dataIO


DUMMY_FILE_PATTERN = 'data/padguide2/{}.dummy'
JSON_FILE_PATTERN = 'data/padguide2/{}.json'
CSV_FILE_PATTERN = 'data/padguide2/{}.csv'

GROUP_BASENAMES_OVERRIDES_SHEET = 'https://docs.google.com/spreadsheets/d/1EoZJ3w5xsXZ67kmarLE4vfrZSIIIAfj04HXeZVST3eY/pub?gid=2070615818&single=true&output=csv'
NICKNAME_OVERRIDES_SHEET = 'https://docs.google.com/spreadsheets/d/1EoZJ3w5xsXZ67kmarLE4vfrZSIIIAfj04HXeZVST3eY/pub?gid=0&single=true&output=csv'

NICKNAME_FILE_PATTERN = CSV_FILE_PATTERN.format('nicknames')
BASENAME_FILE_PATTERN = CSV_FILE_PATTERN.format('basenames')


class PadGuide2(object):
    def __init__(self, bot):
        self.bot = bot
        self.settings = PadGuide2Settings("padguide2")

        self._general_types = [
            PgAttribute,
            PgAwakening,
            PgDungeon,
            PgDungeonMonsterDrop,
            PgDungeonMonster,
            PgEvolution,
            PgEvolutionMaterial,
            PgMonster,
            PgMonsterAddInfo,
            PgMonsterInfo,
            PgMonsterPrice,
            PgSeries,
            PgSkillLeaderData,
            PgSkill,
            PgSkillRotation,
            PgSkillRotationDated,
            PgType,
        ]

        self._download_files()

        # A string -> int mapping, nicknames to monster_id_na
        self.nickname_overrides = {}

        # An int -> set(string), monster_id_na to set of basename overrides
        self.basename_overrides = defaultdict(set)

        self.database = PgRawDatabase(skip_load=True)
#         self.index = MonsterIndex(self.database, self.nickname_overrides, self.basename_overrides)

    def create_index(self, accept_filter=None):
        return MonsterIndex(self.database, self.nickname_overrides, self.basename_overrides, accept_filter=accept_filter)

    def get_monster_by_no(self, monster_no: int):
        return self.database.getMonster(monster_no)

    async def reload_data_task(self):
        await self.bot.wait_until_ready()
        while self == self.bot.get_cog('PadGuide2'):
            short_wait = False
            try:
                self.download_and_refresh_nicknames()
            except Exception as ex:
                short_wait = True
                print("padguide2 data download/refresh failed", ex)
                traceback.print_exc()

            try:
                wait_time = 60 if short_wait else 60 * 60 * 4
                await asyncio.sleep(wait_time)
            except Exception as ex:
                print("padguide2 data wait loop failed", ex)
                traceback.print_exc()
                raise ex

    def download_and_refresh_nicknames(self):
        self._download_files()

        nickname_overrides = self._csv_to_key_value_map(NICKNAME_FILE_PATTERN)
        basename_overrides = self._csv_to_key_value_map(BASENAME_FILE_PATTERN)

        self.nickname_overrides = {k.lower(): int(v)
                                   for k, v in nickname_overrides.items() if v.isdigit()}

        self.basename_overrides = defaultdict(set)
        for k, v in basename_overrides.items():
            if k.isdigit():
                self.basename_overrides[int(k)].add(v.lower())

        self.database = PgRawDatabase()
        self.index = MonsterIndex(self.database, self.nickname_overrides, self.basename_overrides)

    def _load_overrides(self, file_path: str):
        # Loads a two-column CSV into a dict, and cleans it a bit by ensuring the
        # key is lowercase and the value is an integer.
        data = self._csv_to_key_value_map(file_path)
        return

    def _csv_to_key_value_map(self, file_path: str):
        # Loads a two-column CSV into a dict.
        results = {}
        with open(file_path, encoding='utf-8') as f:
            file_reader = csv.reader(f, delimiter=',')
            for row in file_reader:
                if len(row) < 2:
                    continue
                key = row[0].strip()
                value = row[1].strip()

                if not (len(key) and len(value)):
                    continue

                results[key] = value
        return results

    def _download_files(self):
        # Use a dummy file to proxy for the entire database being out of date
        # twelve hours expiry
        general_dummy_file = DUMMY_FILE_PATTERN.format('general')
        general_expiry_secs = 12 * 60 * 60
        if not rpadutils.checkPadguideCacheFile(general_dummy_file, general_expiry_secs):
            return

        # Need to add something that downloads if missing
        for type in self._general_types:
            file_name = type.file_name()
            result_file = JSON_FILE_PATTERN.format(file_name)
            rpadutils.makeCachedPadguideRequest2(file_name, result_file)

        overrides_expiry_secs = 1 * 60 * 60
        rpadutils.makeCachedPlainRequest2(
            NICKNAME_FILE_PATTERN, NICKNAME_OVERRIDES_SHEET, overrides_expiry_secs)
        rpadutils.makeCachedPlainRequest2(
            BASENAME_FILE_PATTERN, GROUP_BASENAMES_OVERRIDES_SHEET, overrides_expiry_secs)

    @commands.group(pass_context=True)
    async def padguide2(self, ctx):
        """PAD database management"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @padguide2.command(pass_context=True)
    @checks.is_owner()
    async def query(self, ctx, query: str):
        m, err, debug_info = self.index.find_monster(query)
        if m is None:
            await self.bot.say(box("no result"))
        else:
            msg = "{}. {}".format(m.monster_no_na, m.name_na)
            msg += "\n group_basenames: {}".format(m.group_basenames)
            msg += "\n prefixes: {}".format(m.prefixes)
            msg += "\n is_low_priority: {}".format(m.is_low_priority)
            msg += "\n group_size: {}".format(m.group_size)
            msg += "\n rarity: {}".format(m.rarity)
            msg += "\n monster_basename: {}".format(m.monster_basename)
            msg += "\n group_computed_basename: {}".format(m.group_computed_basename)
            msg += "\n extra_nicknames: {}".format(m.extra_nicknames)
            msg += "\n final_nicknames: {}".format(m.final_nicknames)
            msg += "\n final_two_word_nicknames: {}".format(m.final_two_word_nicknames)
            await self.bot.say(box(msg))


class PadGuide2Settings(CogSettings):
    def make_default_settings(self):
        config = {
        }
        return config


def setup(bot):
    n = PadGuide2(bot)
    bot.add_cog(n)
    bot.loop.create_task(n.reload_data_task())


class PgRawDatabase(object):
    def __init__(self, skip_load=False):
        self._skip_load = skip_load
        self._all_pg_items = []

        # Load raw data items into id->value maps
        self._attribute_map = self._load(PgAttribute)
        self._awakening_map = self._load(PgAwakening)
        self._dungeon_map = self._load(PgDungeon)
        self._dungeon_monster_drop_map = self._load(PgDungeonMonsterDrop)
        self._dungeon_monster_map = self._load(PgDungeonMonster)
        self._evolution_map = self._load(PgEvolution)
        self._evolution_material_map = self._load(PgEvolutionMaterial)
        self._monster_map = self._load(PgMonster)
        self._monster_add_info_map = self._load(PgMonsterAddInfo)
        self._monster_info_map = self._load(PgMonsterInfo)
        self._monster_price_map = self._load(PgMonsterPrice)
        self._series_map = self._load(PgSeries)
        self._skill_leader_data_map = self._load(PgSkillLeaderData)
        self._skill_map = self._load(PgSkill)
        self._skill_rotation_map = self._load(PgSkillRotation)
        self._skill_rotation_dated_map = self._load(PgSkillRotationDated)
        self._type_map = self._load(PgType)

        # Ensure that every item has loaded its dependencies
        for i in self._all_pg_items:
            self._ensure_loaded(i)

        # Finish loading now that all the dependencies are resolved
        for i in self._all_pg_items:
            i.finalize()

        # Stick the monsters into groups so that we can calculate info across
        # the entire group
        self.grouped_monsters = list()
        for m in self._monster_map.values():
            if m.cur_evo_type != EvoType.Base:
                continue
            self.grouped_monsters.append(MonsterGroup(m))

        # Used to normalize from monster NA values back to monster number
        self.monster_no_na_to_monster_no = {
            m.monster_no_na: m.monster_no for m in self._monster_map.values()}

    def _load(self, itemtype):
        if self._skip_load:
            return {}

        file_path = JSON_FILE_PATTERN.format(itemtype.file_name())
        item_list = []

        if dataIO.is_valid_json(file_path):
            json_data = dataIO.load_json(file_path)
            item_list = [itemtype(item) for item in json_data['items']]

        result_map = {item.key(): item for item in item_list if not item.deleted()}

        self._all_pg_items.extend(result_map.values())

        return result_map

    def _ensure_loaded(self, item: 'PgItem'):
        if item:
            item.ensure_loaded(self)
        return item

    def normalize_monster_no_na(self, monster_no_na: int):
        return self.monster_no_na_to_monster_no[monster_no_na]

    def getAttributeEnum(self, ta_seq: int):
        attr = self._ensure_loaded(self._attribute_map.get(ta_seq))
        return attr.value if attr else None

    def getAwakening(self, tma_seq: int):
        return self._ensure_loaded(self._awakening_map.get(tma_seq))

    def getDungeon(self, dungeon_seq: int):
        return self._ensure_loaded(self._dungeon_map.get(dungeon_seq))

    def getDungeonMonsterDrop(self, tdmd_seq: int):
        return self._ensure_loaded(self._dungeon_monster_drop_map.get(tdmd_seq))

    def getDungeonMonster(self, tdm_seq: int):
        return self._ensure_loaded(self._dungeon_monster_map.get(tdm_seq))

    def getEvolution(self, tv_seq: int):
        return self._ensure_loaded(self._evolution_map.get(tv_seq))

    def getEvolutionMaterial(self, tem_seq: int):
        return self._ensure_loaded(self._evolution_material_map.get(tem_seq))

    def getMonster(self, monster_no: int):
        return self._ensure_loaded(self._monster_map.get(monster_no))

    def getMonsterAddInfo(self, monster_no: int):
        return self._ensure_loaded(self._monster_add_info_map.get(monster_no))

    def getMonsterInfo(self, monster_no: int):
        return self._ensure_loaded(self._monster_info_map.get(monster_no))

    def getMonsterPrice(self, monster_no: int):
        return self._ensure_loaded(self._monster_price_map.get(monster_no))

    def getSeries(self, tsr_seq: int):
        return self._ensure_loaded(self._series_map.get(tsr_seq))

    def getSkill(self, ts_seq: int):
        return self._ensure_loaded(self._skill_map.get(ts_seq))

    def getSkillLeaderData(self, ts_seq: int):
        return self._ensure_loaded(self._skill_leader_data_map.get(ts_seq))

    def getSkillRotation(self, tsr_seq: int):
        return self._ensure_loaded(self._skill_rotation_map.get(tsr_seq))

    def getSkillRotationDated(self, tsrl_seq: int):
        return self._ensure_loaded(self._skill_rotation_dated_map.get(tsrl_seq))

    def getTypeName(self, tt_seq: int):
        type = self._ensure_loaded(self._type_map.get(tt_seq))
        return type.name if type else None


class PgItem(object):
    """Base class for all items loaded from PadGuide.

    You must call super().__init__() in your constructor.
    You must override key() and load().
    """

    def __init__(self):
        self._loaded = False

    def key(self):
        """Used to look up an item by id."""
        raise NotImplementedError()

    def deleted(self):
        """Is this item marked for deletion. Discard if true. Not all items can be deleted."""
        return False

    def ensure_loaded(self, database: PgRawDatabase):
        """Ensures that the dependencies have been loaded, or loads them."""
        if not self._loaded:
            self._loaded = True
            self.load(database)

        return self

    def load(self, database: PgRawDatabase):
        """Override to inject dependencies."""
        raise NotImplementedError()

    def finalize(self):
        """Finish filling in anything that requires completion but no dependencies."""
        pass


class Attribute(Enum):
    """Standard 5 PAD colors in enum form. Values correspond to PadGuide values."""
    Fire = 1
    Water = 2
    Wood = 3
    Light = 4
    Dark = 5


# attributeList.jsp
# {
#     "ORDER_IDX": "2",
#     "TA_NAME_JP": "\u6c34",
#     "TA_NAME_KR": "\ubb3c",
#     "TA_NAME_US": "Water",
#     "TA_SEQ": "2",
#     "TSTAMP": "1372947975226"
# },
class PgAttribute(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item):
        super().__init__()
        self.ta_seq = int(item['TA_SEQ'])  # unique id
        self.name = item['TA_NAME_US']

        self.value = Attribute(self.ta_seq)

    def key(self):
        return self.ta_seq

    def load(self, database: PgRawDatabase):
        pass


# awokenSkillList.jsp
# {
#     "DEL_YN": "N",
#     "MONSTER_NO": "661",
#     "ORDER_IDX": "1",
#     "TMA_SEQ": "1",
#     "TSTAMP": "1380587210665",
#     "TS_SEQ": "2769"
# },
class PgAwakening(PgItem):
    @staticmethod
    def file_name():
        return 'awokenSkillList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tma_seq = int(item['TMA_SEQ'])  # unique id
        self.ts_seq = int(item['TS_SEQ'])  # PgSkill id - awakening info
        self.deleted_yn = item['DEL_YN']  # Either Y(discard) or N.
        self.monster_no = int(item['MONSTER_NO'])  # PgMonster id - monster this belongs to
        self.order = int(item['ORDER_IDX'])  # display order

        self.skill = None  # type: PgSkill  # The awakening skill
        self.monster = None  # type: PgMonster # The monster the awakening belongs to

    def key(self):
        return self.tma_seq

    def deleted(self):
        return self.deleted_yn == 'Y'

    def load(self, database: PgRawDatabase):
        self.skill = database.getSkill(self.ts_seq)
        self.monster = database.getMonster(self.monster_no)

        self.monster.awakenings.append(self)
        self.skill.monsters_with_awakening.append(self.monster)

    def get_name(self):
        return self.skill.name

# dungeonList.jsp
# {
#     "APP_VERSION": "",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "",
#     "COMMENT_US": "",
#     "DUNGEON_SEQ": "102",
#     "DUNGEON_TYPE": "1",
#     "ICON_SEQ": "666",
#     "NAME_JP": "ECO\u30b3\u30e9\u30dc",
#     "NAME_KR": "ECO \ucf5c\ub77c\ubcf4",
#     "NAME_US": "ECO Collab",
#     "ORDER_IDX": "3",
#     "SHOW_YN": "1",
#     "TDT_SEQ": "10",
#     "TSTAMP": "1373289123410"
# },


class PgDungeon(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonList.jsp'

    def __init__(self, item):
        super().__init__()
        self.dungeon_seq = int(item['DUNGEON_SEQ'])
        self.type = DungeonType(int(item['DUNGEON_TYPE']))
        self.name = item['NAME_US']
#         self.tdt_seq = int(item['TDT_SEQ']) # What is this used for?
        self.show_yn = item["SHOW_YN"]

    def key(self):
        return self.dungeon_seq

    def deleted(self):
        # TODO: Is show y/n the same as deleted?
        return False

    def load(self, database: PgRawDatabase):
        pass


# dungeonMonsterDropList.jsp
# {
#     "MONSTER_NO": "3427",
#     "ORDER_IDX": "20",
#     "STATUS": "0",
#     "TDMD_SEQ": "967",
#     "TDM_SEQ": "17816",
#     "TSTAMP": "1489371218890"
# },
# Seems to be dedicated skillups only, like collab drops
class PgDungeonMonsterDrop(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonMonsterDropList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tdmd_seq = int(item['TDMD_SEQ'])  # unique id
        self.monster_no = int(item['MONSTER_NO'])
        self.status = item['STATUS']  # if 1, good, if 0, bad
        self.tdm_seq = int(item['TDM_SEQ'])  # PgDungeonMonster id

        self.monster = None  # type: PgMonster
        self.dungeon_monster = None  # type: PgDungeonMonster

    def key(self):
        return self.tdmd_seq

    def deleted(self):
        # TODO: Should we be checking status == 1?
        return False

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)
        self.dungeon_monster = database.getDungeonMonster(self.tdm_seq)


# dungeonMonsterList.jsp
# {
#     "AMOUNT": "1",
#     "ATK": "9810",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "",
#     "COMMENT_US": "",
#     "DEF": "340",
#     "DROP_NO": "2789",
#     "DUNGEON_SEQ": "150",
#     "FLOOR": "5",
#     "HP": "3011250",
#     "MONSTER_NO": "2789",
#     "ORDER_IDX": "50",
#     "TDM_SEQ": "53122",
#     "TSD_SEQ": "4564",
#     "TSTAMP": "1480298353178",
#     "TURN": "1"
# },
class PgDungeonMonster(PgItem):
    @staticmethod
    def file_name():
        return 'dungeonMonsterList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tdm_seq = int(item['TDM_SEQ'])  # unique id
        self.drop_monster_no = int(item['DROP_NO'])  # PgMonster unique id
        self.monster_no = int(item['MONSTER_NO'])  # PgMonster unique id
        self.dungeon_seq = int(item['DUNGEON_SEQ'])  # PgDungeon uniqueId
        self.tsd_seq = int(item['TSD_SEQ'])  # ??

    def key(self):
        return self.tdm_seq

    def load(self, database: PgRawDatabase):
        self.drop_monster = database.getMonster(self.drop_monster_no)
        self.monster = database.getMonster(self.monster_no)
        self.dungeon = database.getDungeon(self.dungeon_seq)

        if self.drop_monster:
            self.drop_monster.drop_dungeons.append(self.dungeon)


class EvoType(Enum):
    """Evo types supported by PadGuide. Numbers correspond to their id values."""
    Base = -1  # Represents monsters who didn't require evo
    Evo = 0
    UvoAwoken = 1
    UuvoReincarnated = 2


# evolutionList.jsp
# {
#     "APP_VERSION": "",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "",
#     "COMMENT_US": "",
#     "MONSTER_NO": "1",
#     "TO_NO": "2",
#     "TSTAMP": "1371788673999",
#     "TV_SEQ": "331",
#     "TV_TYPE": "0"
# },
class PgEvolution(PgItem):
    @staticmethod
    def file_name():
        return 'evolutionList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tv_seq = int(item['TV_SEQ'])  # unique id
        self.from_monster_no = int(item['MONSTER_NO'])  # PgMonster id - base monster
        self.to_monster_no = int(item['TO_NO'])  # PgMonster id - target monster
        self.tv_type = int(item['TV_TYPE'])
        self.evo_type = EvoType(self.tv_type)

    def key(self):
        return self.tv_seq

    def deleted(self):
        # Really rare and unusual bug
        return self.from_monster_no == 0 or self.to_monster_no == 0

    def load(self, database: PgRawDatabase):
        self.from_monster = database.getMonster(self.from_monster_no)
        self.to_monster = database.getMonster(self.to_monster_no)

        self.to_monster.cur_evo_type = self.evo_type
        self.to_monster.evo_from = self.from_monster
        self.from_monster.evo_to.append(self.to_monster)


# evoMaterialList.jsp
# {
#     "MONSTER_NO": "153",
#     "ORDER_IDX": "1",
#     "TEM_SEQ": "1429",
#     "TSTAMP": "1371788674011",
#     "TV_SEQ": "332"
# },
class PgEvolutionMaterial(PgItem):
    @staticmethod
    def file_name():
        return 'evoMaterialList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tem_seq = int(item['TEM_SEQ'])  # unique id
        self.tv_seq = int(item['TV_SEQ'])  # evo id
        self.fodder_monster_no = int(item['MONSTER_NO'])  # material monster
        self.order = int(item['ORDER_IDX'])  # display order

        self.evolution = None  # type: PgEvolution
        self.fodder_monster = None  # type: PgMonster

    def key(self):
        return self.tem_seq

    def load(self, database: PgRawDatabase):
        self.evolution = database.getEvolution(self.tv_seq)
        self.fodder_monster = database.getMonster(self.fodder_monster_no)

        if self.evolution is None:
            # Really rare and unusual bug
            return

        target_monster = self.evolution.to_monster
        # TODO: this is unsorted
        target_monster.mats_for_evo.append(self.fodder_monster)
        self.fodder_monster.material_of.append(target_monster)


# monsterAddInfoList.jsp
# {
#     "EXTRA_VAL1": "1",
#     "EXTRA_VAL2": "",
#     "EXTRA_VAL3": "",
#     "EXTRA_VAL4": "",
#     "EXTRA_VAL5": "",
#     "MONSTER_NO": "3329",
#     "SUB_TYPE": "0",
#     "TSTAMP": "1480435906788"
# },
class PgMonsterAddInfo(PgItem):
    """Optional extra information for a Monster.

    Data is copied into PgMonster and this is discarded."""

    @staticmethod
    def file_name():
        return 'monsterAddInfoList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.sub_type = int(item['SUB_TYPE'])
        self.extra_val_1 = int_or_none(item['EXTRA_VAL1'])

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        pass


# monsterInfoList.jsp
# {
#     "FODDER_EXP": "675.0",
#     "HISTORY_JP": "[2016-12-16] \u65b0\u898f\u8ffd\u52a0",
#     "HISTORY_KR": "[2016-12-16] \uc2e0\uaddc\ucd94\uac00",
#     "HISTORY_US": "[2016-12-16] New Added",
#     "MONSTER_NO": "3382",
#     "ON_KR": "1",
#     "ON_US": "1",
#     "PAL_EGG": "0",
#     "RARE_EGG": "0",
#     "SELL_PRICE": "300.0",
#     "TSR_SEQ": "86",
#     "TSTAMP": "1481846935838"
# },
class PgMonsterInfo(PgItem):
    """Extra information for a Monster.

    Data is copied into PgMonster and this is discarded."""

    @staticmethod
    def file_name():
        return 'monsterInfoList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.on_na = item['ON_US'] == '1'
        self.tsr_seq = int_or_none(item['TSR_SEQ'])  # PgSeries id
        self.in_pem = item['PAL_EGG'] == '1'
        self.in_rem = item['RARE_EGG'] == '1'

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        self.series = database.getSeries(self.tsr_seq)


# monsterList.jsp
# {
#     "APP_VERSION": "0.0",
#     "ATK_MAX": "1985",
#     "ATK_MIN": "695",
#     "COMMENT_JP": "",
#     "COMMENT_KR": "\uc77c\ubcf8",
#     "COMMENT_US": "Japan",
#     "COST": "60",
#     "EXP": "10000000",
#     "HP_MAX": "6258",
#     "HP_MIN": "3528",
#     "LEVEL": "99",
#     "MONSTER_NO": "3646",
#     "MONSTER_NO_JP": "3646",
#     "MONSTER_NO_KR": "3646",
#     "MONSTER_NO_US": "3646",
#     "PRONUNCIATION_JP": "\u304b\u306a\u305f\u306a\u308b\u3082\u306e\u30fb\u3088\u3050\u305d\u3068\u30fc\u3059",
#     "RARITY": "7",
#     "RATIO_ATK": "1.5",
#     "RATIO_HP": "1.5",
#     "RATIO_RCV": "1.5",
#     "RCV_MAX": "233",
#     "RCV_MIN": "926",
#     "REG_DATE": "2017-04-27 17:29:48.0",
#     "TA_SEQ": "4",
#     "TA_SEQ_SUB": "0",
#     "TE_SEQ": "14",
#     "TM_NAME_JP": "\u5f7c\u65b9\u306a\u308b\u3082\u306e\u30fb\u30e8\u30b0\uff1d\u30bd\u30c8\u30fc\u30b9",
#     "TM_NAME_KR": "\u5f7c\u65b9\u306a\u308b\u3082\u306e\u30fb\u30e8\u30b0\uff1d\u30bd\u30c8\u30fc\u30b9",
#     "TM_NAME_US": "\u5f7c\u65b9\u306a\u308b\u3082\u306e\u30fb\u30e8\u30b0\uff1d\u30bd\u30c8\u30fc\u30b9",
#     "TSTAMP": "1494033700775",
#     "TS_SEQ_LEADER": "12448",
#     "TS_SEQ_SKILL": "12447",
#     "TT_SEQ": "10",
#     "TT_SEQ_SUB": "1"
# }
class PgMonster(PgItem):
    @staticmethod
    def file_name():
        return 'monsterList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.monster_no_na = int(item['MONSTER_NO_US'])
        self.monster_no_jp = int(item['MONSTER_NO_JP'])
        self.hp = int(item['HP_MAX'])
        self.atk = int(item['ATK_MAX'])
        self.rcv = int(item['RCV_MAX'])
        self.ts_seq_active = int_or_none(item['TS_SEQ_SKILL'])
        self.ts_seq_leader = int_or_none(item['TS_SEQ_LEADER'])
        self.rarity = int(item['RARITY'])
        self.cost = int(item['COST'])
        self.max_level = int(item['LEVEL'])
        self.name_na = item['TM_NAME_US']
        self.name_jp = item['TM_NAME_JP']
        self.ta_seq_1 = int(item['TA_SEQ'])  # PgAttribute id
        self.ta_seq_2 = int(item['TA_SEQ_SUB'])  # PgAttribute id
        self.te_seq = int(item['TE_SEQ'])
        self.tt_seq_1 = int(item['TT_SEQ'])  # PgType id
        self.tt_seq_2 = int(item['TT_SEQ_SUB'])  # PgType id

        self.debug_info = ''
        self.weighted_stats = int(self.hp / 10 + self.atk / 5 + self.rcv / 3)

        self.roma_subname = None
        if self.name_na == self.name_jp:
            self.roma_subname = make_roma_subname(self.name_jp)
        else:
            # Remove annoying stuff from NA names, like Jörmungandr
            self.name_na = rpadutils.rmdiacritics(self.name_na)

        self.active_skill = None  # type: PgSkill
        self.leader_skill = None  # type: PgSkill

        # ???
        self.cur_evo_type = EvoType.Base
        self.evo_to = []
        self.evo_from = None

        self.mats_for_evo = []
        self.material_of = []

        self.awakenings = []  # PgAwakening
        self.drop_dungeons = []

        self.alt_evos = []  # PgMonster

        self.server_actives = {}  # str -> ?
        self.server_skillups = {}  # str -> ?


#         self.monster_ids_with_skill = monster_ids_with_skill
#         self.monsters_with_skill = list()

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        self.active_skill = database.getSkill(self.ts_seq_active)
        if self.active_skill:
            self.active_skill.monsters_with_active.append(self)

        self.leader_skill = database.getSkill(self.ts_seq_leader)
        self.leader_skill_data = database.getSkillLeaderData(self.ts_seq_leader)
        if self.leader_skill:
            self.leader_skill.monsters_with_leader.append(self)

        self.attr1 = database.getAttributeEnum(self.ta_seq_1)
        self.attr2 = database.getAttributeEnum(self.ta_seq_2)

        self.type1 = database.getTypeName(self.tt_seq_1)
        self.type2 = database.getTypeName(self.tt_seq_2)
        self.type3 = None

        assist_setting = None
        monster_add_info = database.getMonsterAddInfo(self.monster_no)
        if monster_add_info:
            self.type3 = database.getTypeName(monster_add_info.sub_type)
            assist_setting = monster_add_info.extra_val_1

        monster_info = database.getMonsterInfo(self.monster_no)
        self.on_na = monster_info.on_na
        self.series = database.getSeries(monster_info.tsr_seq)  # PgSeries
        self.series.monsters.append(self)
        self.is_gfe = self.series.tsr_seq == 34  # godfest
        self.in_pem = monster_info.in_pem
        self.in_rem = monster_info.in_rem
        self.pem_evo = self.in_pem
        self.rem_evo = self.in_rem

        monster_price = database.getMonsterPrice(self.monster_no)
        self.sell_mp = monster_price.sell_mp
        self.buy_mp = monster_price.buy_mp
        self.in_mpshop = self.buy_mp > 0
        self.mp_evo = self.in_mpshop

        if assist_setting == 1:
            self.is_inheritable = True
        elif assist_setting == 2:
            self.is_inheritable = False
        else:
            has_awakenings = len(self.awakenings) > 0
            self.is_inheritable = has_awakenings and self.rarity >= 5 and self.sell_mp > 3000

    def finalize(self):
        self.farmable = len(self.drop_dungeons) > 0
        self.farmable_evo = self.farmable


class MonsterGroup(object):
    """Computes shared values across a tree of monsters and injects them."""

    def __init__(self, base_monster: PgMonster):
        self.base_monster = base_monster
        self.members = list()
        self._recursive_add(base_monster)
        self._initialize_members()

    def _recursive_add(self, m: PgMonster):
        self.members.append(m)
        for em in m.evo_to:
            self._recursive_add(em)

    def _initialize_members(self):
        # Compute tree acquisition status
        farmable_evo, pem_evo, rem_evo, mp_evo = False, False, False, False
        for m in self.members:
            farmable_evo = farmable_evo or m.farmable
            pem_evo = pem_evo or m.in_pem
            rem_evo = rem_evo or m.in_rem
            mp_evo = mp_evo or m.in_mpshop

        # Override tree acquisition status
        for m in self.members:
            m.farmable_evo = farmable_evo
            m.pem_evo = pem_evo
            m.rem_evo = rem_evo
            m.mp_evo = mp_evo


# monsterPriceList.jsp
# {
#     "BUY_PRICE": "0",
#     "MONSTER_NO": "3577",
#     "SELL_PRICE": "99",
#     "TSTAMP": "1492101772974"
# }


class PgMonsterPrice(PgItem):
    @staticmethod
    def file_name():
        return 'monsterPriceList.jsp'

    def __init__(self, item):
        super().__init__()
        self.monster_no = int(item['MONSTER_NO'])
        self.buy_mp = int(item['BUY_PRICE'])
        self.sell_mp = int(item['SELL_PRICE'])

    def key(self):
        return self.monster_no

    def load(self, database: PgRawDatabase):
        pass


# seriesList.jsp
# {
#     "DEL_YN": "N",
#     "NAME_JP": "\u308a\u3093",
#     "NAME_KR": "\uc2ac\ub77c\uc784",
#     "NAME_US": "Slime",
#     "SEARCH_DATA": "\u308a\u3093 Slime \uc2ac\ub77c\uc784",
#     "TSR_SEQ": "3",
#     "TSTAMP": "1380587210667"
# },
class PgSeries(PgItem):
    @staticmethod
    def file_name():
        return 'seriesList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tsr_seq = int(item['TSR_SEQ'])
        self.name = item['NAME_US']
        self.deleted_yn = item['DEL_YN']  # Either Y(discard) or N.

        self.monsters = []

    def key(self):
        return self.tsr_seq

    def deleted(self):
        return self.deleted_yn == 'Y'

    def load(self, database: PgRawDatabase):
        pass


# skillList.jsp
# {
#     "MAG_ATK": "0.0",
#     "MAG_HP": "0.0",
#     "MAG_RCV": "0.0",
#     "ORDER_IDX": "3",
#     "REDUCE_DMG": "0.0",
#     "RTA_SEQ_1": "0",
#     "RTA_SEQ_2": "0",
#     "SEARCH_DATA": "\u6e9c\u3081\u65ac\u308a \u6e9c\u3081\u65ac\u308a \u6e9c\u3081\u65ac\u308a 2\u30bf\u30fc\u30f3\u306e\u9593\u3001\u30c1\u30fc\u30e0\u5185\u306e\u30c9\u30e9\u30b4\u30f3\u30ad\u30e9\u30fc\u306e\u899a\u9192\u6570\u306b\u5fdc\u3058\u3066\u653b\u6483\u529b\u304c\u4e0a\u6607\u3002(1\u500b\u306b\u3064\u304d50%) Increase ATK depending on number of Dragon Killer Awakening Skills on team for 2 turns (50% per each) 2\ud134\uac04 \ud300\ub0b4\uc758 \ub4dc\ub798\uace4 \ud0ac\ub7ec \uac01\uc131 \uac2f\uc218\uc5d0 \ub530\ub77c \uacf5\uaca9\ub825\uc774 \uc0c1\uc2b9 (\uac1c\ub2f9 50%)",
#     "TA_SEQ_1": "0",
#     "TA_SEQ_2": "0",
#     "TSTAMP": "1493861895693",
#     "TS_DESC_JP": "2\u30bf\u30fc\u30f3\u306e\u9593\u3001\u30c1\u30fc\u30e0\u5185\u306e\u30c9\u30e9\u30b4\u30f3\u30ad\u30e9\u30fc\u306e\u899a\u9192\u6570\u306b\u5fdc\u3058\u3066\u653b\u6483\u529b\u304c\u4e0a\u6607\u3002(1\u500b\u306b\u3064\u304d50%)",
#     "TS_DESC_KR": "2\ud134\uac04 \ud300\ub0b4\uc758 \ub4dc\ub798\uace4 \ud0ac\ub7ec \uac01\uc131 \uac2f\uc218\uc5d0 \ub530\ub77c \uacf5\uaca9\ub825\uc774 \uc0c1\uc2b9 (\uac1c\ub2f9 50%)",
#     "TS_DESC_US": "Increase ATK depending on number of Dragon Killer Awakening Skills on team for 2 turns (50% per each)",
#     "TS_NAME_JP": "\u6e9c\u3081\u65ac\u308a",
#     "TS_NAME_KR": "\u6e9c\u3081\u65ac\u308a",
#     "TS_NAME_US": "\u6e9c\u3081\u65ac\u308a",
#     "TS_SEQ": "12478",
#     "TT_SEQ_1": "0",
#     "TT_SEQ_2": "0",
#     "TURN_MAX": "22",
#     "TURN_MIN": "14",
#     "T_CONDITION": "3"
# }
class PgSkill(PgItem):
    @staticmethod
    def file_name():
        return 'skillList.jsp'

    def __init__(self, item):
        super().__init__()
        self.ts_seq = int(item['TS_SEQ'])
        self.name = item['TS_NAME_US']
        self.desc = item['TS_DESC_US']
        self.turn_min = int(item['TURN_MIN'])
        self.turn_max = int(item['TURN_MAX'])

        self.monsters_with_active = []
        self.monsters_with_leader = []
        self.monsters_with_awakening = []

    def key(self):
        return self.ts_seq

    def load(self, database: PgRawDatabase):
        pass


# skillLeaderDataList.jsp
#
# PgSkillLeaderData
# 4 pipe delimited fields, each field is a condition
# Slashes separate effects for conditions
# 1: Code 1=HP, 2=ATK, 3=RCV, 4=Reduction
# 2: Multiplier
# 3: Color restriction (coded)
# 4: Type restriction (coded)
# 5: Combo restriction
#
# Reincarnated Izanagi, 4x + 50% for heal cross, 2x atk 2x rcv for god/dragon/balanced
# {
#     "LEADER_DATA": "4/0.5///|2/4///|2/2//6,1,2/|3/2//6,1,2/",
#     "TSTAMP": "1487553365770",
#     "TS_SEQ": "11695"
# },
# Gold Saint, Shion : 4.5X atk when 3+ light combo
# {
#     "LEADER_DATA": "2/4.5///3",
#     "TSTAMP": "1432940060708",
#     "TS_SEQ": "6661"
# },
# Reincarnated Minerva, 3x damage, 2x damage, color resist
# {
#     "LEADER_DATA": "2/3/1//|2/2///|4/0.5/1,4,5//",
#     "TSTAMP": "1475243514648",
#     "TS_SEQ": "10835"
# },
class PgSkillLeaderData(PgItem):
    @staticmethod
    def file_name():
        return 'skillLeaderDataList.jsp'

    def __init__(self, item):
        super().__init__()
        self.ts_seq = int(item['TS_SEQ'])  # unique id
        self.leader_data = item['LEADER_DATA']

        hp, atk, rcv, resist = (1.0,) * 4
        for mod in self.leader_data.split('|'):
            if not mod.strip():
                continue
            items = mod.split('/')

            code = items[0]
            mult = float(items[1])
            if code == '1':
                hp *= mult
            if code == '2':
                atk *= mult
            if code == '3':
                rcv *= mult
            if code == '4':
                resist *= mult

        self.hp = hp
        self.atk = atk
        self.rcv = rcv
        self.resist = resist

    def key(self):
        return self.ts_seq

    def load(self, database: PgRawDatabase):
        pass

    def get_data(self):
        return self.hp, self.atk, self.rcv, self.resist


# skillRotationList.jsp
# {
#     "MONSTER_NO": "915",
#     "SERVER": "JP",
#     "STATUS": "0",
#     "TSR_SEQ": "2",
#     "TSTAMP": "1481627094573"
# }
class PgSkillRotation(PgItem):
    @staticmethod
    def file_name():
        return 'skillRotationList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tsr_seq = int(item['TSR_SEQ'])  # unique id
        self.monster_no = int(item['MONSTER_NO'])
        self.server = item['SERVER']  # JP, NA, KR
        self.status = item['STATUS']
        # TODO: what does status do?

    def key(self):
        return self.tsr_seq

    def deleted(self):
        return self.server == 'KR'  # We don't do KR

    def load(self, database: PgRawDatabase):
        self.monster = database.getMonster(self.monster_no)


# skillRotationListList.jsp
# {
#     "ROTATION_DATE": "2016-12-14",
#     "STATUS": "0",
#     "TSRL_SEQ": "960",
#     "TSR_SEQ": "86",
#     "TSTAMP": "1481627993157",
#     "TS_SEQ": "9926"
# }
class PgSkillRotationDated(PgItem):
    @staticmethod
    def file_name():
        return 'skillRotationListList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tsrl_seq = int(item['TSRL_SEQ'])  # unique id
        self.tsr_seq = int(item['TSR_SEQ'])  # PgSkillRotation id - Current skillup monster
        self.ts_seq = int(item['TS_SEQ'])  # PGSkill id - Current skill
        self.rotation_date_str = item['ROTATION_DATE']

        self.rotation_date = None
        if len(self.rotation_date_str):
            self.rotation_date = datetime.strptime(self.rotation_date_str, "%Y-%m-%d").date()

    def key(self):
        return self.tsrl_seq

    def load(self, database: PgRawDatabase):
        self.skill = database.getSkill(self.ts_seq)
        self.skill_rotation = database.getSkillRotation(self.tsr_seq)


class PgMergedRotation:
    def __init__(self, rotation, dated_rotation):
        self.monster_id = rotation.monster_id
        self.server = rotation.server
        self.rotation_date = dated_rotation.rotation_date
        self.active_id = dated_rotation.active_id

        self.resolved_monster = None  # The monster that does the skillup
        self.resolved_active = None  # The skill for this server


# typeList.jsp
# {
#     "ORDER_IDX": "2",
#     "TSTAMP": "1375363406092",
#     "TT_NAME_JP": "\u60aa\u9b54",
#     "TT_NAME_KR": "\uc545\ub9c8",
#     "TT_NAME_US": "Devil",
#     "TT_SEQ": "10"
# },
class PgType(PgItem):
    @staticmethod
    def file_name():
        return 'typeList.jsp'

    def __init__(self, item):
        super().__init__()
        self.tt_seq = int(item['TT_SEQ'])  # unique id
        self.name = item['TT_NAME_US']

    def key(self):
        return self.tt_seq

    def load(self, database: PgRawDatabase):
        pass


class PgMonsterDropInfoCombined(object):
    def __init__(self, monster_id, dungeon_monster_drop, dungeon_monster, dungeon):
        self.monster_id = monster_id
        self.dungeon_monster_drop = dungeon_monster_drop
        self.dungeon_monster = dungeon_monster
        self.dungeon = dungeon


# ================================================================================
# Items below are deferred (padrem, padevents)
#
#
#
#
# ================================================================================

class RemType(Enum):
    godfest = '1'
    rare = '2'
    pal = '3'
    unknown1 = '4'


class RemRowType(Enum):
    subsection = '0'
    divider = '1'


# eggTitleList.jsp
#       {
#            "DEL_YN": "N",
#            "END_DATE": "2016-10-24 07:59:00",
#            "ORDER_IDX": "0",
#            "SERVER": "US",
#            "SHOW_YN": "Y",
#            "START_DATE": "2016-10-17 08:00:00",
#            "TEC_SEQ": "2",
#            "TET_SEQ": "64",
#            "TSTAMP": "1476490114488",
#            "TYPE": "1"
#        },
class PgEggInstance(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item):
        self.server = normalizeServer(item['SERVER'])
        self.delete = item['DEL_YN']  # Y, N
        self.show = item['SHOW_YN']  # Y, N
        self.rem_type = RemType(item['TEC_SEQ'])  # matches RemType
        self.egg_id = item['TET_SEQ']  # primary key
        self.row_type = RemRowType(item['TYPE'])  # 0-> row with just name, 1-> row with date

        self.order = int(item["ORDER_IDX"])
        self.start_date_str = item['START_DATE']
        self.end_date_str = item['END_DATE']

        tz = pytz.UTC
        self.start_datetime = None
        self.end_datetime = None
        self.open_date_str = None

        self.pt_date_str = None
        if len(self.start_date_str):
            self.start_datetime = datetime.strptime(
                self.start_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            self.end_datetime = datetime.strptime(
                self.end_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)

            if self.server == 'NA':
                pt_tz_obj = pytz.timezone('America/Los_Angeles')
                self.open_date_str = self.start_datetime.replace(tzinfo=pt_tz_obj).strftime('%m/%d')
            if self.server == 'JP':
                jp_tz_obj = pytz.timezone('Asia/Tokyo')
                self.open_date_str = self.start_datetime.replace(tzinfo=jp_tz_obj).strftime('%m/%d')


# eggTitleNameList.jsp
#        {
#            "DEL_YN": "N",
#            "LANGUAGE": "US",
#            "NAME": "Batman Egg",
#            "TETN_SEQ": "183",
#            "TET_SEQ": "64",
#            "TSTAMP": "1441589491425"
#        },
class PgEggName(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item):
        self.name = item['NAME']
        self.language = item['LANGUAGE']  # US, JP, KR
        self.delete = item['DEL_YN']  # Y, N
        self.primary_id = item['TETN_SEQ']  # primary key
        self.egg_id = item['TET_SEQ']  # fk to PgEggInstance


def makeBlankEggName(egg_id):
    return PgEggName({
        'NAME': '',
        'LANGUAGE': 'US',
        'DEL_YN': 'N',
        'TETN_SEQ': '',
        'TET_SEQ': egg_id
    })

# eggMonsterList.jsp
#        {
#            "DEL_YN": "Y",
#            "MONSTER_NO": "120",
#            "ORDER_IDX": "1",
#            "TEM_SEQ": "1",
#            "TET_SEQ": "1",
#            "TSTAMP": "1405245537715"
#        },


class PgEggMonster(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item):
        self.delete = item['DEL_YN']
        self.monster_id = item['MONSTER_NO']
        self.tem_seq = item['TEM_SEQ']  # primary key
        self.egg_id = item['TET_SEQ']  # fk to PgEggInstance

    def key(self):
        return self.tem_seq


TIME_FMT = """%a %b %d %H:%M:%S %Y"""


class EventType(Enum):
    EventTypeWeek = 0
    EventTypeSpecial = 1
    EventTypeSpecialWeek = 2
    EventTypeGuerrilla = 3
    EventTypeGuerrillaNew = 4
    EventTypeEtc = -100


class DungeonType(Enum):
    Unknown = -1
    Normal = 0
    CoinDailyOther = 1
    Technical = 2
    Etc = 3


class TdtType(Enum):
    Normal = 0
    SpecialOther = 1
    Technical = 2
    Weekly = 2
    Descended = 3


def fmtTime(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def fmtTimeShort(dt):
    return dt.strftime("%H:%M")


def fmtHrsMins(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return '{:2}h {:2}m'.format(int(hours), int(minutes))


def fmtDaysHrsMinsShort(sec):
    days = sec // 86400
    sec -= 86400 * days
    hours = sec // 3600
    sec -= 3600 * hours
    minutes = sec // 60

    if days > 0:
        return '{:2}d {:2}h'.format(int(days), int(hours))
    elif hours > 0:
        return '{:2}h {:2}m'.format(int(hours), int(minutes))
    else:
        return '{:2}m'.format(int(minutes))


def normalizeServer(server):
    server = server.upper()
    return 'NA' if server == 'US' else server


def isEventWanted(event):
    name = event.nameAndModifier().lower()
    if 'castle of satan' in name:
        # eliminate things like : TAMADRA Invades in [Castle of Satan][Castle of Satan in the Abyss]
        return False

    return True


def cleanDungeonNames(name):
    if 'tamadra invades in some tech' in name.lower():
        return 'Latents invades some Techs & 20x +Eggs'
    if '1.5x Bonus Pal Point in multiplay' in name:
        name = '[Descends] 1.5x Pal Points in multiplay'
    name = name.replace('No Continues', 'No Cont')
    name = name.replace('No Continue', 'No Cont')
    name = name.replace('Some Limited Time Dungeons', 'Some Guerrillas')
    name = name.replace('are added in', 'in')
    name = name.replace('!', '')
    name = name.replace('Dragon Infestation', 'Dragons')
    name = name.replace(' Infestation', 's')
    name = name.replace('Daily Descended Dungeon', 'Daily Descends')
    name = name.replace('Chance for ', '')
    name = name.replace('Jewel of the Spirit', 'Spirit Jewel')
    name = name.replace(' & ', '/')
    name = name.replace(' / ', '/')
    name = name.replace('PAD Radar', 'PADR')
    name = name.replace('in normal dungeons', 'in normals')
    name = name.replace('Selected ', 'Some ')
    name = name.replace('Enhanced ', 'Enh ')
    name = name.replace('All Att. Req.', 'All Att.')
    name = name.replace('Extreme King Metal Dragon', 'Extreme KMD')
    name = name.replace('Golden Mound-Tricolor [Fr/Wt/Wd Only]', 'Golden Mound')
    name = name.replace('Gods-Awakening Materials Descended', "Awoken Mats")
    name = name.replace('Orb move time 4 sec', '4s move time')
    name = name.replace('Awakening Materials Descended', 'Awkn Mats')
    name = name.replace("Star Treasure Thieves' Den", 'STTD')
    name = name.replace('Ruins of the Star Vault', 'Star Vault')
    return name


class PgEventList(PgItem):
    def __init__(self, event_list):
        self.event_list = event_list

    def withFunc(self, func, exclude=False):
        if exclude:
            return PgEventList(list(itertools.filterfalse(func, self.event_list)))
        else:
            return PgEventList(list(filter(func, self.event_list)))

    def withServer(self, server):
        return self.withFunc(lambda e: e.server == normalizeServer(server))

    def withType(self, event_type):
        return self.withFunc(lambda e: e.event_type == event_type)

    def withDungeonType(self, dungeon_type, exclude=False):
        return self.withFunc(lambda e: e.dungeon_type == dungeon_type, exclude)

    def withNameContains(self, name, exclude=False):
        return self.withFunc(lambda e: name.lower() in e.dungeon_name.lower(), exclude)

    def excludeUnwantedEvents(self):
        return self.withFunc(isEventWanted)

    def items(self):
        return self.event_list

    def startedOnly(self):
        return self.withFunc(lambda e: e.isStarted())

    def pendingOnly(self):
        return self.withFunc(lambda e: e.isPending())

    def activeOnly(self):
        return self.withFunc(lambda e: e.isActive())

    def availableOnly(self):
        return self.withFunc(lambda e: e.isAvailable())

    def itemsByOpenTime(self, reverse=False):
        return list(sorted(self.event_list, key=(lambda e: (e.open_datetime, e.dungeon_name)), reverse=reverse))

    def itemsByCloseTime(self, reverse=False):
        return list(sorted(self.event_list, key=(lambda e: (e.close_datetime, e.dungeon_name)), reverse=reverse))


class PgEvent(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item, ignore_bad=False):
        if item is None and ignore_bad:
            return
        self.server = normalizeServer(item['SERVER'])
        self.dungeon_code = item['DUNGEON_SEQ']
        self.dungeon_name = 'Unknown(' + self.dungeon_code + ')'
        self.dungeon_type = DungeonType.Unknown
        self.event_type = EventType(int(item['EVENT_TYPE']))
        self.event_seq = item['EVENT_SEQ']
        self.event_modifier = ''
        self.uid = item['SCHEDULE_SEQ']

        team_data = item['TEAM_DATA']
        self.group = ''
        if self.event_type in (EventType.EventTypeGuerrilla, EventType.EventTypeGuerrillaNew) and team_data != '':
            self.group = chr(ord('a') + int(team_data)).upper()

        tz = pytz.UTC
        open_time_str = item['OPEN_DATE'] + " " + item['OPEN_HOUR'] + ":" + item['OPEN_MINUTE']
        close_time_strstr = item['CLOSE_DATE'] + " " + \
            item['CLOSE_HOUR'] + ":" + item['CLOSE_MINUTE']

        self.open_datetime = datetime.strptime(open_time_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        self.close_datetime = datetime.strptime(
            close_time_strstr, "%Y-%m-%d %H:%M").replace(tzinfo=tz)

    def updateDungeonName(self, dungeon_seq_map):
        if self.dungeon_code in dungeon_seq_map:
            dungeon = dungeon_seq_map[self.dungeon_code]
            self.dungeon_name = dungeon.name
            self.dungeon_type = dungeon.type

    def updateEventModifier(self, event_modifier_map):
        if self.event_seq in event_modifier_map:
            self.event_modifier = event_modifier_map[self.event_seq].name

    def isForNormal(self):
        return self.dungeon_type == '0'

    def nameAndModifier(self):
        output = self.name()
        if self.event_modifier != '':
            output += ', ' + self.event_modifier.replace('!', '').replace(' ', '')
        return output

    def name(self):
        output = cleanDungeonNames(self.dungeon_name)
        return output

    def tostr(self):
        return fmtTime(self.open_datetime) + "," + fmtTime(self.close_datetime) + "," + self.group + "," + self.dungeon_code + "," + self.event_type + "," + self.event_seq

    def startPst(self):
        tz = pytz.timezone('US/Pacific')
        return self.open_datetime.astimezone(tz)

    def startEst(self):
        tz = pytz.timezone('US/Eastern')
        return self.open_datetime.astimezone(tz)

    def isStarted(self):
        now = datetime.now(pytz.utc)
        delta_open = self.open_datetime - now
        return delta_open.total_seconds() <= 0

    def isFinished(self):
        now = datetime.now(pytz.utc)
        delta_close = self.close_datetime - now
        return delta_close.total_seconds() <= 0

    def isActive(self):
        return self.isStarted() and not self.isFinished()

    def isPending(self):
        return not self.isStarted()

    def isAvailable(self):
        return not self.isFinished()

    def startFromNow(self):
        now = datetime.now(pytz.utc)
        delta = self.open_datetime - now
        return fmtHrsMins(delta.total_seconds())

    def endFromNow(self):
        now = datetime.now(pytz.utc)
        delta = self.close_datetime - now
        return fmtHrsMins(delta.total_seconds())

    def endFromNowFullMin(self):
        now = datetime.now(pytz.utc)
        delta = self.close_datetime - now
        return fmtDaysHrsMinsShort(delta.total_seconds())

    def toGuerrillaStr(self):
        return fmtTimeShort(self.startPst())

    def toDateStr(self):
        return self.server + "," + self.group + "," + fmtTime(self.startPst()) + "," + fmtTime(self.startEst()) + "," + self.startFromNow()

    def toPartialEvent(self, pe):
        if self.isStarted():
            return self.group + " " + self.endFromNow() + "   " + self.nameAndModifier()
        else:
            return self.group + " " + fmtTimeShort(self.startPst()) + " " + fmtTimeShort(self.startEst()) + " " + self.startFromNow() + " " + self.nameAndModifier()


class PgEventType(PgItem):
    @staticmethod
    def file_name():
        return 'attributeList.jsp'

    def __init__(self, item):
        self.seq = item['EVENT_SEQ']
        self.name = item['EVENT_NAME_US']


def make_roma_subname(name_jp):
    subname = name_jp.replace('＝', '')
    adjusted_subname = ''
    for part in subname.split('・'):
        roma_part = romkan.to_roma(part)
        # TODO: never finished this up
        roma_part_undiecode = unidecode.unidecode(part)

        if part != roma_part and not rpadutils.containsJp(roma_part):
            adjusted_subname += ' ' + roma_part.strip('-')
    return adjusted_subname.strip()


def int_or_none(maybe_int: str):
    return int(maybe_int) if len(maybe_int) else None


def empty_index():
    return MonsterIndex(PgRawDatabase(skip_load=True), {}, {})


class MonsterIndex(object):
    def __init__(self, monster_database, nickname_overrides, basename_overrides, accept_filter=None):
        # Important not to hold onto anything except IDs here so we don't leak memory
        monster_groups = monster_database.grouped_monsters

        self.attr_short_prefix_map = {
            Attribute.Fire: ['r'],
            Attribute.Water: ['b'],
            Attribute.Wood: ['g'],
            Attribute.Light: ['l'],
            Attribute.Dark: ['d'],
        }
        self.attr_long_prefix_map = {
            Attribute.Fire: ['red', 'fire'],
            Attribute.Water: ['blue', 'water'],
            Attribute.Wood: ['green', 'wood'],
            Attribute.Light: ['light'],
            Attribute.Dark: ['dark'],
        }

        self.series_to_prefix_map = {
            130: ['halloween'],
            136: ['xmas', 'christmas'],
            125: ['summer', 'beach'],
            114: ['school', 'academy', 'gakuen'],
            139: ['new years', 'ny'],
            149: ['wedding', 'bride'],
            154: ['padr'],
        }

        monster_no_na_to_nicknames = defaultdict(set)
        for nickname, monster_no_na in nickname_overrides.items():
            monster_no_na_to_nicknames[monster_no_na].add(nickname)

        named_monsters = []
        for mg in monster_groups:
            group_basename_overrides = basename_overrides.get(mg.base_monster.monster_no_na, [])
            named_mg = NamedMonsterGroup(mg, group_basename_overrides)
            for monster in named_mg.monsters:
                if accept_filter and not accept_filter(monster):
                    continue
                prefixes = self.compute_prefixes(monster)
                extra_nicknames = monster_no_na_to_nicknames[monster.monster_no_na]
                named_monster = NamedMonster(monster, named_mg, prefixes, extra_nicknames)
                named_monsters.append(named_monster)

        # Sort the NamedMonsters into the opposite order we want to accept their nicknames in
        # This order is:
        #  1) High priority first
        #  2) Monsters with larger group sizes
        #  3) Monsters with higher ID values
        def named_monsters_sort(nm: NamedMonster):
            return (not nm.is_low_priority, nm.group_size, nm.monster_no_na)
        named_monsters.sort(key=named_monsters_sort)

        self.all_entries = {}
        self.two_word_entries = {}
        for nm in named_monsters:
            for nickname in nm.final_nicknames:
                self.all_entries[nickname] = nm
            for nickname in nm.final_two_word_nicknames:
                self.two_word_entries[nickname] = nm

        self.all_monsters = named_monsters
        self.all_na_name_to_monsters = {m.name_na.lower(): m for m in named_monsters}
        self.monster_no_na_to_named_monster = {m.monster_no_na: m for m in named_monsters}
        self.monster_no_to_named_monster = {m.monster_no: m for m in named_monsters}

        for nickname, monster_no_na in nickname_overrides.items():
            nm = self.monster_no_na_to_named_monster.get(monster_no_na)
            if nm:
                self.all_entries[nickname] = nm

    def init_index(self):
        pass

    def compute_prefixes(self, m: PgMonster):
        prefixes = set()

        attr1_short_prefixes = self.attr_short_prefix_map[m.attr1]
        attr1_long_prefixes = self.attr_long_prefix_map[m.attr1]
        prefixes.update(attr1_short_prefixes)
        prefixes.update(attr1_long_prefixes)

        if m.attr2 is not None:
            attr2_short_prefixes = self.attr_short_prefix_map[m.attr2]
            for a1 in attr1_short_prefixes:
                for a2 in attr2_short_prefixes:
                    prefixes.add(a1 + a2)
                    prefixes.add(a1 + '/' + a2)

        # TODO: add prefixes based on type

        # Chibi monsters have the same NA name, except lowercased
        if m.name_na != m.name_jp:
            if m.name_na.lower() == m.name_na:
                prefixes.add('chibi')
        elif 'ミニ' in m.name_jp:
            # Guarding this separately to prevent 'gemini' from triggering (e.g. 2645)
            prefixes.add('chibi')

        lower_name = m.name_na.lower()
        awoken = lower_name.startswith('awoken') or '覚醒' in lower_name
        revo = lower_name.startswith('reincarnated') or '転生' in lower_name
        awoken_or_revo = awoken or revo

        # These clauses need to be separate to handle things like 'Awoken Thoth' which are
        # actually Evos but have awoken in the name
        if awoken:
            prefixes.add('a')
            prefixes.add('awoken')

        if revo:
            prefixes.add('revo')
            prefixes.add('reincarnated')

        # Prefixes for evo type
        if m.cur_evo_type == EvoType.Base:
            prefixes.add('base')
        elif m.cur_evo_type == EvoType.Evo:
            prefixes.add('evo')
        elif m.cur_evo_type == EvoType.UvoAwoken and not awoken_or_revo:
            prefixes.add('uvo')
            prefixes.add('uevo')
        elif m.cur_evo_type == EvoType.UuvoReincarnated and not awoken_or_revo:
            prefixes.add('uuvo')
            prefixes.add('uuevo')

        # Collab prefixes
        prefixes.update(self.series_to_prefix_map.get(m.series.tsr_seq, []))

        return prefixes

    def find_monster(self, query):
        query = rpadutils.rmdiacritics(query).lower().strip()

        # id search
        if query.isdigit():
            m = self.monster_no_na_to_named_monster.get(int(query))
            if m is None:
                return None, 'Looks like a monster ID but was not found', None
            else:
                return m, None, "ID lookup"
            # special handling for na/jp

        # TODO: need to handle na_only?

        # handle exact nickname match
        if query in self.all_entries:
            return self.all_entries[query], None, "Exact nickname"

        contains_jp = rpadutils.containsJp(query)
        if len(query) < 2 and contains_jp:
            return None, 'Japanese queries must be at least 2 characters', None
        elif len(query) < 4 and not contains_jp:
            return None, 'Your query must be at least 4 letters', None

        # TODO: this should be a length-limited priority queue
        matches = set()
        # prefix search for nicknames, space-preceeded, take max id
        for nickname, m in self.all_entries.items():
            if nickname.startswith(query + ' '):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, "Space nickname prefix, max of {}".format(len(matches))

        # prefix search for nicknames, take max id
        for nickname, m in self.all_entries.items():
            if nickname.startswith(query):
                matches.add(m)
        if len(matches):
            all_names = ",".join(map(lambda x: x.name_na, matches))
            return self.pickBestMonster(matches), None, "Nickname prefix, max of {}, matches=({})".format(len(matches), all_names)

        # prefix search for full name, take max id
        for nickname, m in self.all_entries.items():
            if (m.name_na.lower().startswith(query) or m.name_jp.lower().startswith(query)):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, "Full name, max of {}".format(len(matches))

        # for nicknames with 2 names, prefix search 2nd word, take max id
        if query in self.two_word_entries:
            return self.two_word_entries[query], None, "Second-word nickname prefix, max of {}".format(len(matches))

        # TODO: refactor 2nd search characteristcs for 2nd word

        # full name contains on nickname, take max id
        for nickname, m in self.all_entries.items():
            if (query in m.name_na.lower() or query in m.name_jp.lower()):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, 'Full name match on nickname, max of {}'.format(len(matches))

        # full name contains on full monster list, take max id

        for m in self.all_monsters:
            if (query in m.name_na.lower() or query in m.name_jp.lower()):
                matches.add(m)
        if len(matches):
            return self.pickBestMonster(matches), None, 'Full name match on full list, max of {}'.format(len(matches))

        # No decent matches. Try near hits on nickname instead
        matches = difflib.get_close_matches(query, self.all_entries.keys(), n=1, cutoff=.8)
        if len(matches):
            return self.all_entries[matches[0]], None, 'Close nickname match'

        # Still no decent matches. Try near hits on full name instead
        matches = difflib.get_close_matches(
            query, self.all_na_name_to_monsters.keys(), n=1, cutoff=.9)
        if len(matches):
            return self.all_na_name_to_monsters[matches[0]], None, 'Close name match'

        # couldn't find anything
        return None, "Could not find a match for: " + query, None

    def pickBestMonster(self, named_monster_list):
        return max(named_monster_list, key=lambda x: (not x.is_low_priority, x.rarity, x.monster_no_na))


class NamedMonsterGroup(object):
    def __init__(self, monster_group: MonsterGroup, basename_overrides: list):
        self.monster_group = monster_group
        self.monsters = monster_group.members
        self.group_size = len(self.monsters)

        self.monster_no_to_basename = {
            m.monster_no: self._compute_monster_basename(m) for m in self.monsters
        }

        self.computed_basename = self._compute_group_basename()
        self.computed_basenames = set([self.computed_basename])
        if '-' in self.computed_basename:
            self.computed_basenames.add(self.computed_basename.replace('-', ' '))

        self.basenames = basename_overrides or self.computed_basenames

    def _compute_monster_basename(self, m: PgMonster):
        basename = m.name_na.lower()
        if ',' in basename:
            name_parts = basename.split(',')
            if name_parts[1].strip().startswith('the '):
                # handle names like 'xxx, the yyy' where xxx is the name
                basename = name_parts[0]
            else:
                # otherwise, grab the chunk after the last comma
                basename = name_parts[-1]

        for x in ['awoken', 'reincarnated']:
            if basename.startswith(x):
                basename = basename.replace(x, '')

        return basename.strip()

    def _compute_group_basename(self):
        def get_basename(x): return self.monster_no_to_basename[x.monster_no]
        sorted_monsters = sorted(self.monsters, key=get_basename)
        grouped = [(c, len(list(cgen))) for c, cgen in groupby(sorted_monsters, get_basename)]
        # TODO: best_tuple selection could be better
        best_tuple = max(grouped, key=itemgetter(1))
        return best_tuple[0]

    def is_low_priority(self):
        return (self._is_low_priority_monster(self.monster_group.base_monster)
                or self._is_low_priority_group(self.monster_group))

    def _is_low_priority_monster(self, m: PgMonster):
        lp_types = ['evolve', 'enhance', 'protected', 'awoken', 'vendor']
        lp_substrings = ['tamadra']
        lp_min_rarity = 2
        name = m.name_na.lower()

        failed_type = m.type1.lower() in lp_types
        failed_ss = any([x in name for x in lp_substrings])
        failed_rarity = m.rarity < lp_min_rarity
        failed_chibi = name == m.name_na
        return failed_type or failed_ss or failed_rarity or failed_chibi

    def _is_low_priority_group(self, mg: MonsterGroup):
        lp_grp_min_rarity = 5
        max_rarity = max(m.rarity for m in mg.members)
        failed_max_rarity = max_rarity < lp_grp_min_rarity
        return failed_max_rarity


class NamedMonster(object):
    def __init__(self, monster: PgMonster, monster_group: NamedMonsterGroup, prefixes: set, extra_nicknames: set):
        # Must not hold onto monster or monster_group!

        # Hold on to the IDs instead
        self.monster_no = monster.monster_no
        self.monster_no_na = monster.monster_no_na

        # This stuff is important for nickname generation
        self.group_basenames = monster_group.basenames
        self.prefixes = prefixes

        # Data used to determine how to rank the nicknames
        self.is_low_priority = monster_group.is_low_priority()
        self.group_size = monster_group.group_size
        self.rarity = monster.rarity

        # Used in fallback searches
        self.name_na = monster.name_na
        self.name_jp = monster.name_jp

        # These are just extra metadata
        self.monster_basename = monster_group.monster_no_to_basename[self.monster_no]
        self.group_computed_basename = monster_group.computed_basename
        self.extra_nicknames = extra_nicknames

        # Compute extra basenames by checking for two-word basenames and using the second half
        self.two_word_basenames = set()
        for basename in self.group_basenames:
            basename_words = basename.split(' ')
            if len(basename_words) == 2:
                self.two_word_basenames.add(basename_words[1])

        # The primary result nicknames
        self.final_nicknames = set()
        # Set the configured override nicknames
        self.final_nicknames.update(self.extra_nicknames)
        # Set the roma subname for JP monsters
        if monster.roma_subname:
            self.final_nicknames.add(monster.roma_subname)

        # For each basename, add nicknames
        for basename in self.group_basenames:
            # Add the basename directly
            self.final_nicknames.add(basename)
            # Add the prefix plus basename, and the prefix with a space between basename
            for prefix in self.prefixes:
                self.final_nicknames.add(prefix + basename)
                self.final_nicknames.add(prefix + ' ' + basename)

        self.final_two_word_nicknames = set()
        # Slightly different process for two-word basenames. Does this make sense? Who knows.
        for basename in self.two_word_basenames:
            self.final_two_word_nicknames.add(basename)
            # Add the prefix plus basename, and the prefix with a space between basename
            for prefix in self.prefixes:
                self.final_two_word_nicknames.add(prefix + basename)
                self.final_two_word_nicknames.add(prefix + ' ' + basename)


# Code that still needs to be added somewhere

#         skill_rotation = padguide.loadJsonToItem('skillRotationList.jsp', padguide.PgSkillRotation)
#         dated_skill_rotation = padguide.loadJsonToItem(
#             'skillRotationListList.jsp', padguide.PgDatedSkillRotation)

#         id_to_skill_rotation = {sr.tsr_seq: sr for sr in skill_rotation}
#         merged_rotation = [padguide.PgMergedRotation(
#             id_to_skill_rotation[dsr.tsr_seq], dsr) for dsr in dated_skill_rotation]

#         skill_id_to_monsters = defaultdict(list)
#         for m in self.full_monster_list:
#             if m.active_skill:
#                 skill_id_to_monsters[m.active_skill.skill_id].append(m)

#         self.computeCurrentRotations(merged_rotation, 'US', NA_TZ_OBJ,
#                                      monster_id_to_monster, skill_map, skill_id_to_monsters)
#         self.computeCurrentRotations(merged_rotation, 'JP', JP_TZ_OBJ,
#                                      monster_id_to_monster, skill_map, skill_id_to_monsters)

#     def computeCurrentRotations(self, merged_rotation, server, server_tz, monster_id_to_monster, skill_map, skill_id_to_monsters):
#         server_now = datetime.now().replace(tzinfo=server_tz).date()
#         active_rotation = [mr for mr in merged_rotation if mr.server ==
#                            server and mr.rotation_date <= server_now]
#         server = normalizeServer(server)
#
#         monsters_to_rotations = defaultdict(list)
#         for ar in active_rotation:
#             monsters_to_rotations[ar.monster_id].append(ar)
#
#         cur_rotations = list()
#         for _, rotations in monsters_to_rotations.items():
#             cur_rotations.append(max(rotations, key=lambda x: x.rotation_date))
#
#         for mr in cur_rotations:
#             mr.resolved_monster = monster_id_to_monster[mr.monster_id]
#             mr.resolved_active = skill_map[mr.active_id]
#
#             mr.resolved_monster.server_actives[server] = mr.resolved_active
#             monsters_with_skill = skill_id_to_monsters[mr.resolved_active.skill_id]
#             for m in monsters_with_skill:
#                 if m.monster_id != mr.resolved_monster.monster_id:
#                     m.server_skillups[server] = mr.resolved_monster
#
#         return cur_rotations

#     def computeMonsterDropInfoCombined(self,
#                                        dungeon_monster_drop_list,  # unused
#                                        dungeon_monster_list,
#                                        dungeon_list):
#         """Stuff for computing monster drops"""
#
#         # TODO: consider merging in dungeon_monster_drop_list info
#         dungeon_id_to_dungeon = {x.seq: x for x in dungeon_list}
#
#         monster_id_to_drop_info = defaultdict(list)
#         for dungeon_monster in dungeon_monster_list:
#             monster_id = dungeon_monster.drop_monster_id
#             dungeon_seq = dungeon_monster.dungeon_seq
#
#             if dungeon_seq not in dungeon_id_to_dungeon:
#                 # In case downloaded files are out of sync, skip
#                 continue
#             dungeon = dungeon_id_to_dungeon[dungeon_seq]
#
#             info = padguide.PgMonsterDropInfoCombined(monster_id, None, dungeon_monster, dungeon)
#             monster_id_to_drop_info[monster_id].append(info)
#
#         return monster_id_to_drop_info


def compute_killers(*types):
    if 'Balance' in types:
        return ['Any']
    killers = set()
    for t in types:
        killers.update(type_to_killers_map.get(t, []))
    return sorted(killers)


type_to_killers_map = {
    'God': ['Devil'],
    'Devil': ['God'],
    'Machine': ['God', 'Balance'],
    'Dragon': ['Machine', 'Healer'],
    'Physical': ['Machine', 'Healer'],
    'Attacker': ['Devil', 'Physical'],
    'Healer': ['Dragon', 'Attacker'],
}

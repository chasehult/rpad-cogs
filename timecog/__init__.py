from .timecog import TimeCog

def setup(bot):
    n = TimeCog(bot)
    bot.add_cog(n)

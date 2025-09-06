from .main import GatusMetrics

async def setup(bot):
    await bot.add_cog(GatusMetrics(bot))

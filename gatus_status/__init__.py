from .main import GatusStatus


async def setup(bot):
    await bot.add_cog(GatusStatus(bot))

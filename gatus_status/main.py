
import discord
from redbot.core import commands, Config, checks
from datetime import datetime, timedelta, timezone
import re
from typing import Dict, List
import logging
from dataclasses import dataclass

log = logging.getLogger("red.gatus_status")

@dataclass
class GatusData:
    labber: str
    date: datetime
    status: bool

@dataclass
class GatusEvent:
    length: timedelta
    end_data: datetime
    status: bool


class GatusTimeline:
    def __init__(self, name: str):
        self.history: List[GatusEvent] = []
        self.name = name

    def add_entry(self, entry: GatusData):
        if not self.history:
            self.history.append(GatusEvent(length=timedelta(0), end_data=entry.date, status=not entry.status))
            return

        last_event = self.history[-1]
        if last_event.status == entry.status:
            self.history.append(GatusEvent(length=(entry.date - last_event.end_data), end_data=entry.date, status=not entry.status))
        else:

    @property
    def end(self):
        return GatusEvent(length=(datetime.now(timezone.utc) - self.history[-1].end_data), end_data=datetime.now(timezone.utc), status=not self.history[-1].status)


    @classmethod
    def from_data(cls, gatus_data: list[GatusData]) -> list["GatusTimeline"]:
        timelines: Dict[str, GatusTimeline] = {}
        for entry in gatus_data:
            if entry.labber not in timelines:
                timelines[entry.labber] = GatusTimeline(name=entry.labber)
            timelines[entry.labber].add_entry(entry)

        return list(timelines.values())

    def total_events(self, event: bool) -> int:
        offset = 0
        if self.history and self.history[0].status == event:
            offset = -1
        if self.end.status == event:
            offset += 1
        return len([e for e in self.history if e.status == event]) + offset

    def total_time(self, event: bool) -> timedelta:
        offset = timedelta(0)
        if self.end.status == event:
            offset = self.end.length

        return sum([e.length for e in self.history if e.status == event], timedelta(0)) + offset

    @property
    def total_downs(self):
        return self.total_events(False)

    @property
    def total_ups(self):
        return self.total_events(True)

    @property
    def total_time_down(self):
        return self.total_time(False)

    @property
    def total_time_up(self):
        return self.total_time(True)


class GatusStatus(commands.Cog):
    """A cog to scan Discord channels and aggregate useful metrics."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2864893244)

        # Default guild settings
        default_guild = {
            "target_channel": None,
        }

        self.config.register_guild(**default_guild)

    @commands.group(name="gatus_status", aliases=["gs"])
    @commands.guild_only()
    async def gatus_status(self, ctx):
        """UTC Total channel analysis commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @gatus_status.command(name="setchannel", aliases=["sc"])
    @checks.admin_or_permissions(manage_channels=True)
    async def set_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel to analyze for metrics.

        If no channel is provided, uses the current channel.
        """
        if channel is None:
            channel = ctx.channel

        await self.config.guild(ctx.guild).target_channel.set(channel.id)
        await ctx.send(f"✅ Set target channel to {channel.mention}")

    @gatus_status.command(name="metrics", aliases=["m"])
    async def get_metrics(self, ctx, days: int | None = None):
        """Generate metrics for the configured channel or specified channel.

        Args:
            channel: Channel to analyze (optional, uses configured channel if not specified)
            days: Number of days to look back (default: 7)
        """
        # Determine which channel to analyze
        target_channel_id = await self.config.guild(ctx.guild).target_channel()
        if not target_channel_id:
            await ctx.send("❌ No target channel configured. Use `utctotal setchannel` first or specify a channel.")
            return
        channel = ctx.guild.get_channel(target_channel_id)
        if not channel:
            await ctx.send("❌ Configured target channel not found.")
            return

        if days is None:
            analyse_days = 7
        else:
            analyse_days = days
        # Send initial message
        loading_msg = await ctx.send("🔍 Analyzing channel for metrics...")

        try:
            with ctx.typing():
                embed = await self._create_metrics_embed(channel, analyse_days)

                await loading_msg.edit(content="", embed=embed)
        except Exception as e:
            log.exception("Error during channel analysis")
            await loading_msg.edit(content=f"❌ Error during analysis: {str(e)}")

    async def _create_metrics_embed(self, channel: discord.TextChannel, days: int) -> discord.Embed:
        history = channel.history(limit=None, after=datetime.now(timezone.utc) - timedelta(days=days))

        data = await self.get_gatus_data(history)
        timelines = GatusTimeline.from_data(data)

        # Create the main embed
        embed = discord.Embed(
            title="📊 UTC Total Metrics",
            description=f"Analysis for the last {days} day(s) in {channel.mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        # Add overall statistics
        total_labbers = len(timelines)
        embed.add_field(
            name="📈 Overview",
            value=f"**Total Services:** {total_labbers}\n**Analysis Period:** {days} days",
            inline=False
        )

        # Add detailed stats for each labber
        if timelines:
            for timeline in timelines:
                # Format uptime/downtime durations
                total_up_time = timeline.total_time_up
                total_down_time = timeline.total_time_down

                # Calculate uptime percentage
                total_time = total_up_time + total_down_time
                if total_time.total_seconds() > 0:
                    uptime_percentage = (total_up_time.total_seconds() / total_time.total_seconds()) * 100
                else:
                    uptime_percentage = 100.0

                # Format time strings
                up_days = total_up_time.days
                up_hours, remainder = divmod(total_up_time.seconds, 3600)
                up_minutes = remainder // 60

                down_days = total_down_time.days
                down_hours, remainder = divmod(total_down_time.seconds, 3600)
                down_minutes = remainder // 60
                current_status = "Up" if timeline.end.status else "Down"

                # Create field value with all timeline properties
                field_value = (
                    f"**Uptime:** {uptime_percentage:.5f}%\n"
                    f"**Total Ups:** {timeline.total_ups}\n"
                    f"**Total Downs:** {timeline.total_downs}\n"
                    f"**Time Up:** {up_days}d {up_hours}h {up_minutes}m\n"
                    f"**Time Down:** {down_days}d {down_hours}h {down_minutes}m\n"
                    f"**Current Status:** {current_status}"
                )

                # Determine status emoji based on uptime
                if uptime_percentage >= 99:
                    status_emoji = "🟢"
                elif uptime_percentage >= 95:
                    status_emoji = "🟡"
                else:
                    status_emoji = "🔴"

                embed.add_field(
                    name=f"{status_emoji} {timeline.name}",
                    value=field_value,
                    inline=True
                )
        else:
            embed.add_field(
                name="ℹ️ No Data",
                value="No Gatus alerts found in the specified time period.",
                inline=False
            )

        embed.set_footer(text="Generated by UTC Total")

        return embed


    async def get_gatus_data(self, history):# -> list[Any]:
        messages = [message async for message in history]
        gattus_data: list[GatusData] = []
        for message in messages:
            for embed in message.embeds:
                if embed.title and ":helmet_with_white_cross: Gatus" in embed.title:
                    gattus_data.append(await self.parse_gatus_embed(embed, message))
        return gattus_data

    async def parse_gatus_embed(self, embed, message):
        message_date = message.created_at
        # Extract labber name from title
        title_match = re.search(r'alert for (.+?) has been', embed.description)
        if title_match:
            name = title_match.group(1)
        else:
            name = "Unknown"

        # Determine status from description
        if ":white_check_mark:" in embed.fields[0].value:
            status = True
        else:
            status = False
        return GatusData(labber=name, date=message_date, status=status)

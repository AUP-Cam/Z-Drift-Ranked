import asyncio
from asyncio import Lock

import discord
from discord.ext import commands

from database import get_json, initialize_database, set_json
from cogs.Comp import RANKINGS_RESET_USER_ID
from cogs.Teams import load_teams, save_teams

QUEUE_CHANNEL_NAME = "team-queue"
MATCHES_CHANNEL_NAME = "team-ranked-matches"
MATCH_MMR_RANGE = 200
MMR_WIN_REWARD = 25

initialize_database()


def load_queue():
    return [int(owner_id) for owner_id in get_json("team_ranked_queue", [])]


def save_queue(queue):
    set_json("team_ranked_queue", queue)


def load_matches():
    return get_json("team_ranked_matches", {})


def save_matches(matches):
    set_json("team_ranked_matches", matches)


def team_for_owner(owner_id):
    return next((team for team in load_teams() if team.get("owner_id") == owner_id), None)


def team_mmr(team):
    return float(team.get("mmr", 0))


def team_players(team):
    return {team["owner_id"], *team.get("members", [])}


def remove_match(message_id):
    matches = load_matches()
    matches.pop(str(message_id), None)
    save_matches(matches)


def migrate_team_mmr():
    teams = load_teams()
    changed = False
    for team in teams:
        if "mmr" not in team:
            team["mmr"] = 0
            changed = True
    if changed:
        save_teams(teams)


class LeagueActivityCheckView(discord.ui.View):
    def __init__(self, owner_ids, responded_owners, completion_event):
        super().__init__(timeout=180)
        self.owner_ids = set(owner_ids)
        self.responded_owners = responded_owners
        self.completion_event = completion_event

    @discord.ui.button(label="I am ready", style=discord.ButtonStyle.success, custom_id="team_ranked_activity_confirm")
    async def confirm_activity(self, interaction, button):
        if interaction.user.id not in self.owner_ids:
            await interaction.response.send_message("Only the team owners can confirm this activity check.", ephemeral=True)
            return
        if interaction.user.id in self.responded_owners:
            await interaction.response.send_message("You have already confirmed this activity check.", ephemeral=True)
            return

        self.responded_owners.add(interaction.user.id)
        await interaction.response.send_message("Your team is confirmed for the match.", ephemeral=True)
        if self.responded_owners == self.owner_ids:
            self.completion_event.set()
            self.stop()


class LeagueResultView(discord.ui.View):
    def __init__(self, team1, team2, message_id=None, thread_id=None, parent_message_id=None, record=None):
        super().__init__(timeout=None)
        record = record or {}
        self.message_id = message_id or record.get("message_id")
        self.thread_id = thread_id or record.get("thread_id")
        self.parent_message_id = parent_message_id or record.get("parent_message_id")
        self.team1 = record.get("team1", team1)
        self.team2 = record.get("team2", team2)
        self.owner_ids = {
            self.team1["owner_id"],
            self.team2["owner_id"],
        }
        self.owner_votes = {
            int(owner_id): int(team)
            for owner_id, team in record.get("owner_votes", {}).items()
        }
        self.cancel_voters = set(record.get("cancel_voters", []))
        self.result_submitted = record.get("result_submitted", False)

    def to_record(self):
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "parent_message_id": self.parent_message_id,
            "team1": self.team1,
            "team2": self.team2,
            "owner_votes": {str(owner_id): team for owner_id, team in self.owner_votes.items()},
            "cancel_voters": list(self.cancel_voters),
            "result_submitted": self.result_submitted,
        }

    async def update_parent(self, interaction, color):
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)
        parent = thread.parent or await interaction.client.fetch_channel(thread.parent_id)
        try:
            message = await parent.fetch_message(self.parent_message_id)
            if message.embeds:
                data = message.embeds[0].to_dict()
                data["color"] = color.value
                await message.edit(embed=discord.Embed.from_dict(data))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def complete(self, interaction, winning_team, override=False):
        if self.result_submitted:
            await interaction.response.send_message("This match has already been resolved.", ephemeral=True)
            return
        self.result_submitted = True
        remove_match(self.message_id)
        winning = self.team1 if winning_team == 1 else self.team2
        teams = load_teams()
        stored_team = next((team for team in teams if team.get("owner_id") == winning["owner_id"]), None)
        if stored_team is not None:
            stored_team["mmr"] = team_mmr(stored_team) + MMR_WIN_REWARD
            save_teams(teams)
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="Team Ranked Match Complete",
            description=f"{winning['team_name']} won the match.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Result", value="Owner override" if override else "Both team owners agreed")
        embed.add_field(name="Winner MMR", value=f"+{MMR_WIN_REWARD}")
        await interaction.response.edit_message(embed=embed, view=self, content=None)
        await self.update_parent(interaction, discord.Color.green())
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)
        await thread.edit(archived=True, locked=True)

    async def result(self, interaction, winning_team):
        if interaction.user.id not in self.owner_ids:
            await interaction.response.send_message("Only the two team owners can report the result.", ephemeral=True)
            return
        if self.result_submitted or interaction.user.id in self.owner_votes:
            await interaction.response.send_message("You cannot submit another result vote.", ephemeral=True)
            return
        self.owner_votes[interaction.user.id] = winning_team
        if len(self.owner_votes) < len(self.owner_ids):
            matches = load_matches()
            matches[str(self.message_id)] = self.to_record()
            save_matches(matches)
            await interaction.response.edit_message(content="Your vote was recorded. Waiting for the other team owner.", view=self)
            return

        votes = set(self.owner_votes.values())
        if len(votes) > 1:
            self.owner_votes.clear()
            matches = load_matches()
            matches[str(self.message_id)] = self.to_record()
            save_matches(matches)
            await interaction.response.edit_message(content="The owners disagreed. The result vote has been restarted.", view=self)
            return

        await self.complete(interaction, winning_team)

    async def cancel(self, interaction):
        if interaction.user.id not in self.owner_ids:
            await interaction.response.send_message("Only the two team owners can cancel this match.", ephemeral=True)
            return
        if self.result_submitted:
            await interaction.response.send_message("This match has already been closed.", ephemeral=True)
            return
        if interaction.user.id in self.cancel_voters:
            await interaction.response.send_message("You have already voted to cancel this match.", ephemeral=True)
            return
        self.cancel_voters.add(interaction.user.id)
        if len(self.cancel_voters) < len(self.owner_ids):
            matches = load_matches()
            matches[str(self.message_id)] = self.to_record()
            save_matches(matches)
            await interaction.response.edit_message(content="Your cancel vote was recorded. Waiting for the other team owner.", view=self)
            return

        await self.complete_cancel(interaction)

    async def complete_cancel(self, interaction, override=False):
        if self.result_submitted:
            await interaction.response.send_message("This match has already been closed.", ephemeral=True)
            return
        self.result_submitted = True
        remove_match(self.message_id)
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="League Match Cancelled",
            description="Owner override" if override else "Both team owners agreed to cancel.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=self, content=None)
        await self.update_parent(interaction, discord.Color.red())
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)
        await thread.edit(archived=True, locked=True)

    @discord.ui.button(label="Team 1 Won", style=discord.ButtonStyle.success, custom_id="league_team_1_won")
    async def team_1_won(self, interaction, button):
        await self.result(interaction, 1)

    @discord.ui.button(label="Team 2 Won", style=discord.ButtonStyle.success, custom_id="league_team_2_won")
    async def team_2_won(self, interaction, button):
        await self.result(interaction, 2)

    @discord.ui.button(label="Cancel Match", style=discord.ButtonStyle.danger, custom_id="league_cancel_match")
    async def cancel_match(self, interaction, button):
        await self.cancel(interaction)

    @discord.ui.button(label="Resolve Team 1", style=discord.ButtonStyle.danger, custom_id="league_resolve_team_1")
    async def resolve_team_1(self, interaction, button):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message("You are not authorized to override this match.", ephemeral=True)
            return
        await self.complete(interaction, 1, override=True)

    @discord.ui.button(label="Resolve Team 2", style=discord.ButtonStyle.danger, custom_id="league_resolve_team_2")
    async def resolve_team_2(self, interaction, button):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message("You are not authorized to override this match.", ephemeral=True)
            return
        await self.complete(interaction, 2, override=True)

    @discord.ui.button(label="Resolve Cancel", style=discord.ButtonStyle.danger, custom_id="league_resolve_cancel")
    async def resolve_cancel(self, interaction, button):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message("You are not authorized to override this match.", ephemeral=True)
            return
        await self.complete_cancel(interaction, override=True)


class LeagueQueueView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Join League Queue", style=discord.ButtonStyle.primary, custom_id="league_join_queue")
    async def join(self, interaction, button):
        await self.cog.join_queue(interaction)

    @discord.ui.button(label="Leave League Queue", style=discord.ButtonStyle.danger, custom_id="league_leave_queue")
    async def leave(self, interaction, button):
        if interaction.user.id not in self.cog.queue:
            await interaction.response.send_message("Your team is not in the league queue.", ephemeral=True)
            return
        self.cog.queue.remove(interaction.user.id)
        save_queue(self.cog.queue)
        await interaction.response.send_message("Your team left the league queue.", ephemeral=True)
        await self.cog.update_queue_message()


class LeagueMatchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        migrate_team_mmr()
        self.queue = load_queue()
        self.queue_message = None
        self.lock = Lock()
        self.restored = False

    async def update_queue_message(self):
        if self.queue_message is not None:
            try:
                await self.queue_message.edit(content=f"League queue: {len(self.queue)} team(s)", view=LeagueQueueView(self))
            except discord.NotFound:
                self.queue_message = None

    async def ensure_queue_message(self):
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=QUEUE_CHANNEL_NAME)
            if channel is None:
                continue
            messages = [message async for message in channel.history(limit=50) if message.author == self.bot.user and message.content.startswith("League queue:")]
            self.queue_message = messages[0] if messages else await channel.send(
                content=f"League queue: {len(self.queue)} team(s)",
                view=LeagueQueueView(self),
            )
            self.bot.add_view(LeagueQueueView(self), message_id=self.queue_message.id)
            await self.update_queue_message()
            for duplicate in messages[1:]:
                await duplicate.delete()

    async def join_queue(self, interaction):
        async with self.lock:
            team = team_for_owner(interaction.user.id)
            if team is None:
                await interaction.response.send_message("Only a team owner with a registered team can join.", ephemeral=True)
                return
            owner_id = team["owner_id"]
            if owner_id in self.queue:
                await interaction.response.send_message("Your team is already in the team queue.", ephemeral=True)
                return
            self.queue.append(owner_id)
            opponent_index = next(
                (index for index, queued_owner in enumerate(self.queue[:-1])
                 if team_for_owner(queued_owner) is not None
                 and abs(team_mmr(team) - team_mmr(team_for_owner(queued_owner))) <= MATCH_MMR_RANGE),
                None,
            )
            if opponent_index is None:
                save_queue(self.queue)
                await interaction.response.send_message("Your team joined the team queue.", ephemeral=True)
            else:
                opponent = team_for_owner(self.queue[opponent_index])
                self.queue.pop()
                self.queue.pop(opponent_index)
                save_queue(self.queue)
                await interaction.response.defer(ephemeral=True)
                await self.create_match(interaction, team, opponent)
            await self.update_queue_message()

    async def create_match(self, interaction, team1, team2):
        owner_ids = {team1["owner_id"], team2["owner_id"]}
        responded_owners = set()
        completion_event = asyncio.Event()
        unavailable_owners = []
        activity_views = []

        for owner_id in owner_ids:
            member = interaction.guild.get_member(owner_id)
            if member is None:
                unavailable_owners.append(owner_id)
                continue
            activity_view = LeagueActivityCheckView(owner_ids, responded_owners, completion_event)
            activity_views.append(activity_view)
            try:
                await member.send(
                    "Activity check: click the button below within 3 minutes to join your league match.\n# BY CLICKING THE BUTTON, YOU CONFIRM THAT YOU AND 3 OTHER PLAYERS ARE READY TO PLAY.",
                    view=activity_view,
                )
            except discord.Forbidden:
                unavailable_owners.append(owner_id)

        if unavailable_owners:
            self.queue.extend(owner_id for owner_id in responded_owners if owner_id not in self.queue)
            save_queue(self.queue)
            await interaction.followup.send(
                "Match cancelled because an activity check could not be sent to every team owner. "
                f"{len(responded_owners)} responding team(s) were returned to the queue.",
                ephemeral=True,
            )
            return

        try:
            await asyncio.wait_for(completion_event.wait(), timeout=180)
        except asyncio.TimeoutError:
            pass

        if responded_owners != owner_ids:
            self.queue.extend(owner_id for owner_id in responded_owners if owner_id not in self.queue)
            save_queue(self.queue)
            for activity_view in activity_views:
                activity_view.stop()
            await interaction.followup.send(
                "Match cancelled because both team owners did not complete the activity check. "
                f"{len(responded_owners)} responding team(s) were returned to the queue.",
                ephemeral=True,
            )
            return

        channel = discord.utils.get(interaction.guild.text_channels, name=MATCHES_CHANNEL_NAME)
        if channel is None:
            self.queue.extend([team1["owner_id"], team2["owner_id"]])
            save_queue(self.queue)
            await interaction.followup.send(f"The `{MATCHES_CHANNEL_NAME}` channel was not found; teams were returned to the queue.", ephemeral=True)
            return
        parent = await channel.send(embed=discord.Embed(title="League Match", description=f"{team1['team_name']} vs {team2['team_name']}", color=discord.Color.orange()))
        thread = await parent.create_thread(name=f"League: {team1['team_name']} vs {team2['team_name']}"[:100])
        embed = discord.Embed(title="League Match", description="Play a best of 3 match. Report the result below when complete.", color=discord.Color.blurple())
        for number, team in enumerate((team1, team2), start=1):
            embed.add_field(name=f"Team {number}: {team['team_name']} ({team_mmr(team):g} MMR)", value=" ".join(f"<@{player_id}>" for player_id in team_players(team)), inline=False)
        await thread.send(embed=embed)
        view = LeagueResultView(team1, team2, thread_id=thread.id, parent_message_id=parent.id)
        result_message = await thread.send(embed=discord.Embed(title="Match Result", description="Select the winning team.", color=discord.Color.green()), view=view)
        view.message_id = result_message.id
        matches = load_matches()
        matches[str(result_message.id)] = view.to_record()
        save_matches(matches)
        await interaction.followup.send("Your team was matched. Check the league-matches thread.", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        if self.restored:
            return
        self.restored = True
        await self.ensure_queue_message()
        for message_id, record in load_matches().items():
            try:
                thread = await self.bot.fetch_channel(record["thread_id"])
                await thread.fetch_message(int(message_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError):
                remove_match(message_id)
                continue
            self.bot.add_view(LeagueResultView(record["team1"], record["team2"], int(message_id), record=record), message_id=int(message_id))


async def setup(bot):
    await bot.add_cog(LeagueMatchmaking(bot))
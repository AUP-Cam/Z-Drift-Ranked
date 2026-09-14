import discord
import asyncio
from asyncio import Lock
from discord.ext import commands
from discord import app_commands

from database import (
    get_bans,
    get_int,
    get_json,
    initialize_database,
    set_int,
    set_json,
)

queue = []
parties = {}
party_invites = {}
ranks = ["Bronze", "Silver", "Gold", "Diamond", "Master"]
GAME_SIZE = 8
CANCEL_VOTES_REQUIRED = 5
RANKINGS_RESET_USER_ID = 584539388747448321
DISABLE_PARTY_CREATION = True
game_creation_lock = Lock()
def load_bans():
    return get_bans()

def load_game_counter():
    return get_int("game_counter")

def load_queue():
    return [int(player_id) for player_id in get_json("current_queue", [])]

def save_queue():
    set_json("current_queue", queue)

initialize_database()
queue.extend(load_queue())
game_counter = load_game_counter()

def load_rankings():
    return {
        int(player_id): float(rating)
        for player_id, rating in get_json("rankings", {}).items()
    }

def save_rankings(rankings):
    set_json("rankings", rankings)

def get_rank_name(rating):
    if rating < 50:
        return "Bronze"
    if rating < 125:
        return "Silver"
    if rating < 225:
        return "Gold"
    if rating < 350:
        return "Diamond"
    return "Master"

def get_party_group(player, available_players):
    available_set = set(available_players)
    partner = parties.get(player)
    if (
        partner in available_set
        and parties.get(partner) == player
    ):
        return [player, partner]
    return [player]

async def assign_rank_role(guild, player_id):
    if guild is None:
        return

    member = guild.get_member(player_id)
    if member is None:
        return

    current_rating = load_rankings().get(player_id, 0)
    target_rank = get_rank_name(current_rating)

    for role_name in ranks:
        role = discord.utils.get(guild.roles, name=role_name)
        if role and role in member.roles:
            await member.remove_roles(role)

    role = discord.utils.get(guild.roles, name=target_rank)
    if role:
        await member.add_roles(role)


def load_current_matches():
    return get_json("current_matches", {})

def save_current_matches(matches):
    set_json("current_matches", matches)

def save_match(view):
    matches = load_current_matches()
    matches[str(view.message_id)] = view.to_record()
    save_current_matches(matches)

def remove_match(message_id):
    matches = load_current_matches()
    matches.pop(str(message_id), None)
    save_current_matches(matches)

def balance_teams(players):
    rankings = load_rankings()
    unranked_players = [player for player in players if player not in rankings]
    if unranked_players:
        for player in unranked_players:
            rankings[player] = 0
        save_rankings(rankings)

    player_set = set(players)
    groups = []
    grouped_players = set()
    average_rating = sum(rankings.get(player, 0) for player in players) / len(players) if players else 0
    for player in players:
        if player in grouped_players:
            continue
        else:
            group = get_party_group(player, player_set)
            groups.append(group)
            grouped_players.update(group)
    
    parties = []
    extra_players = []
    
    for item in groups:
        if len(item) == 1:
            extra_players.append(item[0])
        else:
            parties.append(item)
    
    teams = [[], []]
    if len(parties) == 1:
        teams[0].extend(parties[0])
    elif len(parties) == 2:
        teams[0].extend(parties[0])
        teams[1].extend(parties[1])
    elif len(parties) == 3:
        teams[0].extend(parties[0])
        teams[1].extend(parties[1])
        teams[0].extend(parties[2])
    elif len(parties) == 4:
        teams[0].extend(parties[0])
        teams[1].extend(parties[1])
        teams[0].extend(parties[2])
        teams[1].extend(parties[3])
    elif len(parties) == 0:
        pass  # No players to balance
    else:
        print("Error: More than 4 groups formed, cannot balance teams.")
        return None, None
    team1_rating = sum(rankings.get(player, 0) for player in teams[0])
    team2_rating = sum(rankings.get(player, 0) for player in teams[1])
    for player in extra_players:
        if len(teams[0]) == GAME_SIZE // 2:
            teams[1].append(player)
            team2_rating += rankings.get(player, 0)
        elif len(teams[1]) == GAME_SIZE // 2:
            teams[0].append(player)
            team1_rating += rankings.get(player, 0)
        else:
            if rankings.get(player, 0) > average_rating:
                if team1_rating <= team2_rating:
                    teams[0].append(player)
                    team1_rating += rankings.get(player, 0)
                else:
                    teams[1].append(player)
                    team2_rating += rankings.get(player, 0)
            else:
                if team1_rating <= team2_rating:
                    teams[1].append(player)
                    team2_rating += rankings.get(player, 0)
                else:
                    teams[0].append(player)
                    team1_rating += rankings.get(player, 0)


    return teams[0], teams[1]

def get_game_players():
    selected_players = []
    selected_set = set()
    for player in queue:
        if player in selected_set:
            continue
        group = get_party_group(player, queue)
        if len(selected_players) + len(group) > GAME_SIZE:
            continue
        selected_players.extend(group)
        selected_set.update(group)
        if len(selected_players) == GAME_SIZE:
            return selected_players
    return None

def award_ranking(winning_players,losing_players):
    rankings = load_rankings()
    previous_rankings = {
        player: rankings.get(player, 0)
        for player in winning_players | losing_players
    }
    total = 0
    players = 0
    for player in winning_players:
        total += rankings.get(player, 0)
        players += 1
    for player in losing_players:
        total += rankings.get(player, 0)
        players += 1
    average = total / players if players > 0 else 0
    for player in winning_players:
        rankings[player] += round(min(max(20-pow((rankings.get(player, 0) - average) * 0.02,3), 10), 35))
    for player in losing_players:
        rankings[player] += round(max(min(-17-pow((rankings.get(player, 0) - average) * 0.02,3), -5), -20))

    for player in rankings:
        rankings[player] = max(0, rankings[player])

    save_rankings(rankings)

    return {
        player: (previous_rankings[player], rankings[player])
        for player in previous_rankings
    }

def reset_rankings():
    rankings = load_rankings()
    for player in rankings:
        rankings[player] = 0
    save_rankings(rankings)

def player_names(players, guild):
    return ", ".join(
        guild.get_member(player).display_name
        if guild and guild.get_member(player)
        else str(player)
        for player in players
    )

def player_mentions(players):
    return ", ".join(f"<@{player}>" for player in players)

class ActivityCheckView(discord.ui.View):
    def __init__(self, players, responded_players, completion_event):
        super().__init__(timeout=60)
        self.players = set(players)
        self.responded_players = responded_players
        self.completion_event = completion_event

    @discord.ui.button(label="I am ready", style=discord.ButtonStyle.success)
    async def confirm_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.players:
            await interaction.response.send_message(
                "You are not part of this activity check.",
                ephemeral=True,
            )
            return

        if interaction.user.id in self.responded_players:
            await interaction.response.send_message(
                "You have already confirmed that you are ready.",
                ephemeral=True,
            )
            return

        self.responded_players.add(interaction.user.id)
        await interaction.response.send_message(
            "You are confirmed for the match.",
            ephemeral=True,
        )
        if self.responded_players == self.players:
            self.completion_event.set()
            self.stop()

async def create_game(players, channel, queue_update=None):
    global game_counter
    print(f'Creating game with players: {players}')
    if 0 < len(players) <= GAME_SIZE:
        for player in players:
            if player in queue:
                queue.remove(player)
        save_queue()
        if queue_update is not None:
            await queue_update()

        games_channel = discord.utils.find(
            lambda guild_channel: guild_channel.name.lower() == "zdrift-matches",
            getattr(channel.guild, "text_channels", []),
        )
        if games_channel is None:
            queue.extend(player for player in players if player not in queue)
            save_queue()
            if queue_update is not None:
                await queue_update()
            await channel.send("Error creating game. Please create a text channel named zdrift-matches.")
            return

        responded_players = set()
        completion_event = asyncio.Event()
        unavailable_players = []
        for player_id in players:
            member = channel.guild.get_member(player_id)
            if member is None:
                unavailable_players.append(player_id)
                continue
            try:
                await member.send(
                    "Activity check: click the button below within 1 minute to join the match.",
                    view=ActivityCheckView(players, responded_players, completion_event),
                )
            except (discord.Forbidden, discord.HTTPException):
                unavailable_players.append(player_id)

        if unavailable_players:
            queue.extend(
                player
                for player in players
                if player not in unavailable_players and player not in queue
            )
            save_queue()
            if queue_update is not None:
                await queue_update()
            await channel.send(
                "Match cancelled because an activity check could not be sent to every player. "
                f"{len(unavailable_players)} player(s) were removed from the queue. "
                f"{len(players) - len(unavailable_players)} player(s) were returned to the queue.",
                delete_after=10,
            )
            return False

        try:
            await asyncio.wait_for(completion_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass

        if responded_players != set(players):
            queue.extend(player for player in responded_players if player not in queue)
            save_queue()
            if queue_update is not None:
                await queue_update()
            await channel.send(
                "Match cancelled because not every player completed the activity check. "
                f"{len(responded_players)} player(s) who passed were returned to the queue.",
                delete_after=10,
            )
            return False

        game_counter += 1
        set_int("game_counter", game_counter)
        team1, team2 = balance_teams(players)
        
        game_message = await games_channel.send(
            embed=discord.Embed(
                title=f"Competitive Game #{game_counter}",
                description="A new competitive match has been created.",
                color=discord.Color.orange(),
            )
        )
        game_thread = await game_message.create_thread(name=f"Competitive Game #{game_counter}")
        teams_embed = discord.Embed(
            title=f"Competitive Game #{game_counter}",
            description="Best-of-three match. Coordinate a server **preferably in core** and report the result below.",
            color=discord.Color.blurple(),
        )
        teams_embed.add_field(name="Team 1", value=player_mentions(team1), inline=False)
        teams_embed.add_field(name="Team 2", value=player_mentions(team2), inline=False)
        await game_thread.send(embed=teams_embed)
        await game_thread.send(player_mentions(team1 + team2))
        result_view = GameResultView(
            team1,
            team2,
            thread_id=game_thread.id,
            parent_message_id=game_message.id,
        )
        result_message = await game_thread.send(
            embed=discord.Embed(
                title="Match Result",
                description="Select the winning team when the match is complete.",
                color=discord.Color.green(),
            ),
            view=result_view,
        )
        result_view.message_id = result_message.id
        save_match(result_view)
        return True
    else:
        print(f'Not enough players to create a game. Current queue size: {len(players)}')
        await channel.send("Error creating game. Please rejoin queue.")
        return False

class GameResultView(discord.ui.View):
    def __init__(
        self,
        team1,
        team2,
        message_id=None,
        thread_id=None,
        parent_message_id=None,
        record=None,
    ):
        super().__init__(timeout=None)
        record = record or {}
        self.message_id = message_id or record.get("message_id")
        self.thread_id = thread_id or record.get("thread_id")
        self.parent_message_id = parent_message_id or record.get("parent_message_id")
        self.team1 = set(record.get("team1", team1))
        self.team2 = set(record.get("team2", team2))
        self.players = self.team1 | self.team2
        self.result_votes_required = len(self.players)
        self.cancel_votes_required = min(CANCEL_VOTES_REQUIRED, len(self.players))
        self.votes = {int(key): value for key, value in record.get("votes", {"1": 0, "2": 0}).items()}
        self.voters = set(record.get("voters", []))
        self.cancel_voters = set(record.get("cancel_voters", []))
        self.result_submitted = record.get("result_submitted", False)

    def to_record(self):
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "parent_message_id": self.parent_message_id,
            "team1": list(self.team1),
            "team2": list(self.team2),
            "votes": {str(key): value for key, value in self.votes.items()},
            "voters": list(self.voters),
            "cancel_voters": list(self.cancel_voters),
            "result_submitted": self.result_submitted,
        }

    async def update_parent_embed(self, interaction, color):
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)

        parent = thread.parent
        if parent is None:
            parent = await interaction.client.fetch_channel(thread.parent_id)

        parent_message_id = self.parent_message_id or thread.id
        try:
            parent_message = await parent.fetch_message(parent_message_id)
            if not parent_message.embeds:
                return
            embed_data = parent_message.embeds[0].to_dict()
            embed_data["color"] = color.value
            await parent_message.edit(embed=discord.Embed.from_dict(embed_data))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def submit_result(self, interaction, winning_team):
        if interaction.user.id not in self.players:
            await interaction.response.send_message(
                "Only players in this game can report the result.",
                ephemeral=True,
            )
            return

        if self.result_submitted:
            await interaction.response.send_message(
                "The result for this game has already been reported.",
                ephemeral=True,
            )
            return

        if interaction.user.id in self.voters:
            await interaction.response.send_message(
                "You have already voted on this match.",
                ephemeral=True,
            )
            return
        
        self.voters.add(interaction.user.id)
        self.votes[winning_team] += 1
        save_match(self)
        majority_votes = self.result_votes_required // 2 + 1

        if max(self.votes.values()) < majority_votes:
            vote_embed = discord.Embed(
                title="Match Result Vote",
                description="Your vote has been submitted.",
                color=discord.Color.blurple(),
            )
            vote_embed.add_field(name="Team 1 votes", value=str(self.votes[1]))
            vote_embed.add_field(name="Team 2 votes", value=str(self.votes[2]))
            vote_embed.set_footer(text=f"{len(self.voters)}/{self.result_votes_required} votes submitted")
            await interaction.response.edit_message(embed=vote_embed, view=self)
            return
        
        if max(self.votes.values()) >= majority_votes:
            vote_embed = discord.Embed(
                 title="Match Result Vote",
                description="Your vote has been submitted.",
                color=discord.Color.blurple(),
                )
            vote_embed.add_field(name="Team 1 votes", value=str(self.votes[1]))
            vote_embed.add_field(name="Team 2 votes", value=str(self.votes[2]))
            vote_embed.set_footer(text=f"{len(self.voters)}/{self.result_votes_required} votes submitted")
            await interaction.response.edit_message(embed=vote_embed, view=self)

        self.result_submitted = True
        remove_match(self.message_id)
        winning_team = 1 if self.votes[1] > self.votes[2] else 2
        winning_players = self.team1 if winning_team == 1 else self.team2
        losing_players = self.team2 if winning_team == 1 else self.team1
        ranking_changes = award_ranking(winning_players, losing_players)
        for player in ranking_changes:
            await assign_rank_role(interaction.guild, player)
        ranking_summary = "\n".join(
            f"<@{player}>, {ending_rating - starting_rating:+g} MMR, "
            f"{ending_rating:g} MMR"
            for player, (starting_rating, ending_rating) in ranking_changes.items()
        )
        for child in self.children:
            child.disabled = True
        result_embed = discord.Embed(
            title="Match Complete",
            description=f"Team {winning_team} won the match.",
            color=discord.Color.green(),
        )
        result_embed.add_field(name="Winning votes", value=str(self.votes[winning_team]))
        result_embed.add_field(name="Total votes", value=str(len(self.voters)))
        result_embed.add_field(name="Rating Changes", value=ranking_summary, inline=False)
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)
        try:
            await thread.send(
                embed=discord.Embed(
                    title="Rating Changes",
                    description=ranking_summary,
                    color=discord.Color.gold(),
                )
            )
            await self.update_parent_embed(interaction, discord.Color.green())
        finally:
            await thread.edit(archived=True, locked=True)

    async def submit_cancel(self, interaction):
        if interaction.user.id not in self.players:
            await interaction.response.send_message(
                "Only players in this game can cancel it.",
                ephemeral=True,
            )
            return

        if self.result_submitted:
            await interaction.response.send_message(
                "This game has already been closed.",
                ephemeral=True,
            )
            return

        if interaction.user.id in self.cancel_voters:
            await interaction.response.send_message(
                "You have already voted to cancel this game.",
                ephemeral=True,
            )
            return

        self.cancel_voters.add(interaction.user.id)
        save_match(self)
        if len(self.cancel_voters) < self.cancel_votes_required:
            await interaction.response.edit_message(
                content=(
                    f"Cancel vote submitted. "
                    f"({len(self.cancel_voters)}/{self.cancel_votes_required} cancel votes)"
                ),
                view=self,
            )
            return

        self.result_submitted = True
        remove_match(self.message_id)
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Game Cancelled",
                description=f"The game was cancelled by {self.cancel_votes_required} players.",
                color=discord.Color.red(),
            ),
            view=self,
        )
        await self.update_parent_embed(interaction, discord.Color.red())
        await interaction.channel.edit(archived=True, locked=True)

    async def resolve_cancel(self, interaction):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message(
                "You are not authorized to resolve this cancellation.",
                ephemeral=True,
            )
            return

        if self.result_submitted:
            await interaction.response.send_message(
                "This game has already been closed.",
                ephemeral=True,
            )
            return

        self.result_submitted = True
        remove_match(self.message_id)
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Game Cancelled",
                description="The game cancellation was resolved by an administrator.",
                color=discord.Color.red(),
            ),
            view=self,
        )
        await self.update_parent_embed(interaction, discord.Color.red())
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)
        await thread.edit(archived=True, locked=True)
    
    async def report_result(self, interaction, winning_team):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            return await interaction.response.send_message("you are not authorized to report the result of this game.", ephemeral=True)
        
        winning_players = self.team1 if winning_team == 1 else self.team2
        losing_players = self.team2 if winning_team == 1 else self.team1
        ranking_changes = award_ranking(winning_players, losing_players)
        for player in ranking_changes:
            await assign_rank_role(interaction.guild, player)
        ranking_summary = "\n".join(
            f"<@{player}>, {ending_rating - starting_rating:+g} MMR, "
            f"{ending_rating:g} MMR"
            for player, (starting_rating, ending_rating) in ranking_changes.items()
        )
        for child in self.children:
            child.disabled = True
        result_embed = discord.Embed(
            title="Match Complete",
            description=f"Team {winning_team} won the match.",
            color=discord.Color.green(),
        )
        result_embed.add_field(name="Winning votes", value=str(self.votes[winning_team]))
        result_embed.add_field(name="Total votes", value=str(len(self.voters)))
        result_embed.add_field(name="Rating Changes", value=ranking_summary, inline=False)
        thread = interaction.channel
        if thread is None or thread.id != self.thread_id:
            thread = await interaction.client.fetch_channel(self.thread_id)
        try:
            await thread.send(
                embed=discord.Embed(
                    title="Rating Changes",
                    description=ranking_summary,
                    color=discord.Color.gold(),
                )
            )
            await self.update_parent_embed(interaction, discord.Color.green())
        finally:
            await thread.edit(archived=True, locked=True)
            
            
            self.result_submitted = True
            remove_match(self.message_id)

    @discord.ui.button(label="Team 1 Won", style=discord.ButtonStyle.success, custom_id="team_1_won")
    async def team_1_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.submit_result(interaction, 1)

    @discord.ui.button(label="Team 2 Won", style=discord.ButtonStyle.success, custom_id="team_2_won")
    async def team_2_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.submit_result(interaction, 2)

    @discord.ui.button(label="Cancel Game", style=discord.ButtonStyle.danger, custom_id="cancel_game")
    async def cancel_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.submit_cancel(interaction)

    @discord.ui.button(label="Resolve Cancel", style=discord.ButtonStyle.danger, custom_id="resolve_cancel")
    async def resolve_cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.resolve_cancel(interaction)
    
    @discord.ui.button(label="Resolve Team 1", style=discord.ButtonStyle.danger, custom_id="resolve_team_1")
    async def resolve_team_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.report_result(interaction, 1)

    @discord.ui.button(label="Resolve Team 2", style=discord.ButtonStyle.danger, custom_id="resolve_team_2")
    async def resolve_team_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.report_result(interaction, 2)

class COMP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue_channel = None
        self.queue_message = None
        self.queue_message_lock = Lock()
        self.matches_restored = False
        self.queue_started = False

    async def send_queue_message(self):
        async with self.queue_message_lock:
            content = f"Queue: {len(queue)}/{GAME_SIZE}"
            if self.queue_message is not None:
                try:
                    await self.queue_message.edit(content=content, view=View())
                except discord.NotFound:
                    self.queue_message = None

            existing_messages = [
                message async for message in self.queue_channel.history(limit=50)
                if message.author == self.bot.user and message.content.startswith("Queue:")
            ]
            if existing_messages:
                if self.queue_message is None:
                    self.queue_message = existing_messages[0]
                    await self.queue_message.edit(content=content, view=View())
                for duplicate in existing_messages:
                    if duplicate.id != self.queue_message.id:
                        await duplicate.delete()
                return

            self.queue_message = await self.queue_channel.send(
                content=content,
                view=View(),
            )

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.matches_restored:
            self.matches_restored = True
            for message_id, record in load_current_matches().items():
                try:
                    thread = await self.bot.fetch_channel(record["thread_id"])
                    await thread.fetch_message(int(message_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError):
                    remove_match(message_id)
                    continue

                self.bot.add_view(
                    GameResultView(
                        record.get("team1", []),
                        record.get("team2", []),
                        int(message_id),
                        record=record,
                    ),
                    message_id=int(message_id),
                )
            print(f'Cog {__name__} is ready.')

        if not self.queue_started:
            self.queue_channel = next(
                (
                    channel
                    for guild in self.bot.guilds
                    for channel in guild.text_channels
                    if channel.name == "zdrift-queue"
                ),
                None,
            )
            if self.queue_channel is not None:
                await self.send_queue_message()
                self.queue_started = True
    
    @app_commands.command(name="comp", description="Test Comp")
    async def comp(self, interaction: discord.Interaction):
        embed = discord.Embed(title="COMP SLATE", description="This is a test", color=discord.Color.blue())
        embed.add_field(name="Field 1", value="This is field 1", inline=False)
        embed.add_field(name="Field 2", value="This is field 2", inline=False)
        await interaction.response.send_message(
            content=f"Queue: {len(queue)}/{GAME_SIZE}",
            view=View(),
            embed=embed,
            ephemeral=True,
        )
        
    @app_commands.command(name="start_queue", description="Start (or restart) the queue")
    async def start_queue(self, interaction: discord.Interaction):
        admin_role = (
            discord.utils.get(interaction.guild.roles, name="Admin")
            or discord.utils.get(interaction.guild.roles, name="Admins")
            or discord.utils.get(interaction.guild.roles, name="admin")
        )
        if admin_role is None or admin_role not in interaction.user.roles:
            await interaction.response.send_message(
                "Only users with the Admin role can start the queue.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        queue_channel = discord.utils.get(
            interaction.guild.text_channels,
            name="zdrift-queue",
        )
        if queue_channel is None:
            await interaction.followup.send(
                "The `zdrift-queue` channel was not found.",
                ephemeral=True,
            )
            return

        self.queue_channel = queue_channel
        await self.send_queue_message()
        await interaction.followup.send("Queue started!", ephemeral=True)

    @app_commands.command(name="force_start", description="Start a game with the players currently in queue")
    async def force_start(self, interaction: discord.Interaction):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message(
                "You are not authorized to force start a game.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        async with game_creation_lock:
            if not queue:
                await interaction.followup.send(
                    "There are no players in the queue.",
                    ephemeral=True,
                )
                return

            players = list(queue)
            game_created = await create_game(
                players,
                interaction.channel,
                queue_update=self.send_queue_message,
            )
            if self.queue_channel is not None:
                await self.send_queue_message()
            if not game_created:
                await interaction.followup.send(
                    "The game was not created.",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                f"Started a game with {len(players)} player{'s' if len(players) != 1 else ''}.",
                ephemeral=True,
            )

    @app_commands.command(name="clear_queue", description="Clear all players from the matchmaking queue")
    async def clear_queue(self, interaction: discord.Interaction):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message(
                "You are not authorized to clear the queue.",
                ephemeral=True,
            )
            return

        queue.clear()
        save_queue()
        if self.queue_channel is not None:
            await self.send_queue_message()
        await interaction.response.send_message(
            "The queue has been cleared. Current queue: 0/8.",
            ephemeral=True,
        )
        
    @app_commands.command(name="show_queue", description="Show the current queue")
    async def show_queue(self, interaction: discord.Interaction):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message(
                "Only the bot owner can view the current queue.",
                ephemeral=True,
            )
            return

        names = [
            interaction.guild.get_member(player).display_name
            if interaction.guild and interaction.guild.get_member(player)
            else str(player)
            for player in queue
        ]
        await interaction.response.send_message(f"Current queue: {', '.join(names)}", ephemeral=True)

    @app_commands.command(name="rank", description="Show your current rating")
    async def rank(self, interaction: discord.Interaction):
        rating = load_rankings().get(interaction.user.id, 0)
        await interaction.response.send_message(
            f"Your current rating is {rating:g}.",
            ephemeral=True,
        )

    @app_commands.command(name="leaderboard", description="Show the top 10 players")
    async def leaderboard(self, interaction: discord.Interaction):
        rankings = sorted(
            load_rankings().items(),
            key=lambda player_rating: player_rating[1],
            reverse=True,
        )[:10]

        if not rankings:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Leaderboard",
                    description="The leaderboard is empty.",
                    color=discord.Color.gold(),
                ),
                ephemeral=True,
            )
            return

        entries = []
        for position, (player_id, rating) in enumerate(rankings, start=1):
            member = interaction.guild.get_member(player_id) if interaction.guild else None
            player_name = member.display_name if member else str(player_id)
            entries.append(f"{position}. {player_name} - {rating:g}")

        leaderboard_embed = discord.Embed(
            title="Leaderboard",
            description="Top 10 ranked players",
            color=discord.Color.gold(),
        )
        leaderboard_embed.add_field(name="Rankings", value="\n".join(entries), inline=False)
        await interaction.response.send_message(embed=leaderboard_embed, ephemeral=True)

    @app_commands.command(name="reset_rankings", description="Reset all player ratings to zero")
    async def reset_rankings_command(self, interaction: discord.Interaction):
        if interaction.user.id != RANKINGS_RESET_USER_ID:
            await interaction.response.send_message(
                "You are not authorized to reset the rankings.",
                ephemeral=True,
            )
            return

        reset_rankings()
        await interaction.response.send_message(
            "All player ratings have been reset to 0.",
            ephemeral=True,
        )

    @app_commands.command(name="fix_ranks", description="Apply the correct rank role to every server member")
    async def fix_ranks(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Only server administrators can fix ranks.",
                ephemeral=True,
            )
            return

        missing_roles = [
            rank
            for rank in ranks
            if discord.utils.get(interaction.guild.roles, name=rank) is None
        ]
        if missing_roles:
            await interaction.response.send_message(
                "Create these rank roles first: " + ", ".join(missing_roles),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        fixed_members = 0
        failed_members = 0
        for member in interaction.guild.members:
            try:
                if member.id == self.bot.user.id:
                    continue
                else:
                    await assign_rank_role(interaction.guild, member.id)
                    fixed_members += 1
            except discord.Forbidden:
                failed_members += 1

        result = f"Applied ranks to {fixed_members} server member{'s' if fixed_members != 1 else ''}."
        if failed_members:
            result += f" Could not update {failed_members} member{'s' if failed_members != 1 else ''} due to role permissions."
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(name="party_invite", description="Invite a player to your matchmaking party")
    @app_commands.describe(player="The player you want to invite")
    async def party_invite(self, interaction: discord.Interaction, player: discord.Member):
        if DISABLE_PARTY_CREATION:
            await interaction.response.send_message("The party system is currently disabled.", ephemeral=True)
            return
        inviter_id = interaction.user.id
        if player.id == inviter_id:
            await interaction.response.send_message("You cannot invite yourself.", ephemeral=True)
            return
        if inviter_id in parties or player.id in parties:
            await interaction.response.send_message("One of you is already in a party.", ephemeral=True)
            return

        party_invites[player.id] = inviter_id
        await interaction.response.send_message(
            f"Party invitation sent to {player.mention}. They can use `/party_accept` to join.",
            ephemeral=True,
        )

    @app_commands.command(name="party_accept", description="Accept your pending matchmaking party invitation")
    async def party_accept(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        inviter_id = party_invites.pop(player_id, None)
        if inviter_id is None:
            await interaction.response.send_message("You do not have a pending party invitation.", ephemeral=True)
            return
        if inviter_id in parties or player_id in parties:
            await interaction.response.send_message("One of you is already in a party.", ephemeral=True)
            return

        parties[player_id] = inviter_id
        parties[inviter_id] = player_id
        await interaction.response.send_message(
            "Party accepted. You will be matched on the same team.",
            ephemeral=True,
        )
    
    @app_commands.command(name="purge_queue", description="Remove all players from the matchmaking queue and clear all parties")
    async def purge_queue(self, interaction: discord.Interaction):
        if "admin" not in [role.name for role in interaction.user.roles]:
            await interaction.response.send_message(
                "You are not authorized to purge the queue.",
                ephemeral=True,
            )
            return

        queue.clear()
        parties.clear()
        party_invites.clear()
        save_queue()
        self.send_queue_message()
        await interaction.response.send_message(
            "The queue and all parties have been purged.",
            ephemeral=True,
        )

    @app_commands.command(name="party_info", description="Show your current party member")
    async def party_info(self, interaction: discord.Interaction):
        party_member_id = parties.get(interaction.user.id)
        if party_member_id is None:
            await interaction.response.send_message(
                "You are not currently in a party.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Your current party member is <@{party_member_id}>.",
            ephemeral=True,
        )

    @app_commands.command(name="party_disband", description="Disband your current matchmaking party")
    async def party_disband(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        party_member_id = parties.pop(player_id, None)
        if party_member_id is None:
            await interaction.response.send_message(
                "You are not currently in a party.",
                ephemeral=True,
            )
            return

        parties.pop(party_member_id, None)
        party_invites.pop(player_id, None)
        party_invites.pop(party_member_id, None)
        await interaction.response.send_message(
            "Your party has been disbanded.",
            ephemeral=True,
        )

class View(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.primary, custom_id="button_click")
    async def button_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with game_creation_lock:
            banned_ids = load_bans()
            if str(interaction.user.id) in banned_ids:
                await interaction.response.send_message("You are banned and cannot join the queue.", ephemeral=True)
                return

            if interaction.user.id in queue:
                await interaction.response.send_message("You are already in the queue.", ephemeral=True)
                return

            queue.append(interaction.user.id)
            players = get_game_players()
            if players is not None:
                await interaction.response.defer(ephemeral=True)
                async def update_queue_message():
                    await interaction.message.edit(
                        content=f"Queue: {len(queue)}/{GAME_SIZE}",
                        view=self,
                    )

                await create_game(
                    players,
                    interaction.channel,
                    queue_update=update_queue_message,
                )
                await interaction.followup.send("Joined Queue!", ephemeral=True)
            else:
                save_queue()
                await interaction.response.send_message("Joined Queue!", ephemeral=True)
            await interaction.message.edit(content=f"Queue: {len(queue)}/{GAME_SIZE}", view=self)
        
    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.danger, custom_id="button_leave")
    async def button_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in queue:
            queue.remove(interaction.user.id)
            save_queue()
            await interaction.response.send_message("Left Queue!", ephemeral=True)
            await interaction.message.edit(content=f"Queue: {len(queue)}/{GAME_SIZE}", view=self)
        else:
            await interaction.response.send_message("You are not in the queue.", ephemeral=True)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(COMP(bot))
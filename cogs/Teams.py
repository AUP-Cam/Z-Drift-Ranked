from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from database import get_json, initialize_database, set_json

initialize_database()

def load_teams():
    return get_json("league_teams", [])


def save_teams(teams):
    set_json("league_teams", teams)


def load_team_requests():
    return get_json("team_requests", [])


def save_team_requests(requests):
    set_json("team_requests", requests)


def load_rankings():
    return {
        int(player_id): float(rating)
        for player_id, rating in get_json("rankings", {}).items()
    }


def load_scrim_requests():
    return get_json("scrim_requests", [])


def save_scrim_requests(requests):
    set_json("scrim_requests", requests)


def load_scrim_threads():
    return get_json("scrim_threads", [])


def save_scrim_threads(threads):
    set_json("scrim_threads", threads)


def remove_scrim_request(guild_id, owner_id, target_timestamp):
    requests = [
        request for request in load_scrim_requests()
        if not (
            request.get("guild_id") == guild_id
            and request.get("owner_id") == owner_id
            and request.get("target_timestamp") == target_timestamp
        )
    ]
    save_scrim_requests(requests)


def scrim_request_embed(request):
    adaptive_time = f"<t:{request['target_timestamp']}:F>"
    embed = discord.Embed(
        title="Scrim Request",
        description=f"**{request['team_name']}** is looking for a scrim.",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Scheduled", value=adaptive_time, inline=True)
    embed.add_field(name="Owner", value=f"<@{request['owner_id']}>", inline=True)
    embed.add_field(name="Region", value=request["region"], inline=True)
    embed.set_footer(text="If time has passed, this request may no longer be valid, but you may still accept it")
    return embed


def get_team_for_owner(owner_id):
    return next(
        (team for team in load_teams() if team.get("owner_id") == owner_id),
        None,
    )


def team_name_exists(teams, team_name, exclude_owner_id=None):
    normalized_name = team_name.strip().casefold()
    return any(
        team.get("team_name", "").strip().casefold() == normalized_name
        and team.get("owner_id") != exclude_owner_id
        for team in teams
    )


def get_pending_requests_for_team(team_name):
    return [
        request for request in load_team_requests()
        if request.get("team_name") == team_name
    ]


def get_requests_for_player(player_id):
    return [
        request for request in load_team_requests()
        if request.get("player_id") == player_id
    ]


def get_team_for_player(player_id):
    for team in load_teams():
        if team.get("owner_id") == player_id:
            return team
        if player_id in team.get("members", []):
            return team
    return None


def format_team_summary(team: dict, label: str):
    owner_id = team.get("owner_id")
    members = team.get("members", [])
    member_mentions = " ".join(f"<@{member_id}>" for member_id in members) if members else "No accepted members"

    return (
        f"**{label}: {team.get('team_name', 'Unknown Team')}** ({team.get('region', 'Unknown')})\n"
        f"Owner: <@{owner_id}>\n"
        f"Members: {member_mentions}"
    )


def team_embed(team: dict, title: str):
    embed = discord.Embed(
        title=title,
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Team", value=team.get("team_name", "Unknown Team"), inline=True)
    embed.add_field(name="Region", value=team.get("region", "Unknown"), inline=True)
    embed.add_field(name="Owner", value=f"<@{team.get('owner_id')}>", inline=False)
    members = team.get("members", [])
    member_mentions = " ".join(f"<@{member_id}>" for member_id in members) if members else "No accepted members"
    embed.add_field(name="Members", value=member_mentions, inline=False)
    return embed


class ScrimAcceptView(discord.ui.View):
    def __init__(self, team_name: str, owner_id: int, region: str, target_timestamp: int):
        super().__init__(timeout=None)
        self.team_name = team_name
        self.owner_id = owner_id
        self.region = region
        self.target_timestamp = target_timestamp
        self.accepted = False
        self.cancelled = False

    @discord.ui.button(label="Accept Scrim", style=discord.ButtonStyle.success, custom_id="accept_scrim")
    async def accept_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cancelled:
            await interaction.response.send_message(
                "This scrim request has been cancelled.",
                ephemeral=True,
            )
            return

        if self.accepted:
            await interaction.response.send_message(
                "This scrim has already been accepted.",
                ephemeral=True,
            )
            return

        challenger_team = next(
            (team for team in load_teams() if team.get("team_name") == self.team_name and team.get("owner_id") == self.owner_id),
            None,
        )
        if challenger_team is None:
            await interaction.response.send_message(
                "This scrim request is no longer valid.",
                ephemeral=True,
            )
            return

        accepting_team = get_team_for_owner(interaction.user.id)
        if accepting_team is None:
            await interaction.response.send_message(
                "Only a team owner can accept a scrim.",
                ephemeral=True,
            )
            return

        if accepting_team.get("team_name") == self.team_name and accepting_team.get("owner_id") == self.owner_id:
            await interaction.response.send_message(
                "You cannot accept your own team's scrim request.",
                ephemeral=True,
            )
            return

        self.accepted = True
        remove_scrim_request(interaction.guild.id, self.owner_id, self.target_timestamp)
        button.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Scrim Accepted",
                description=f"**{self.team_name}** vs **{accepting_team['team_name']}**",
                color=discord.Color.green(),
            ).add_field(
                name="Scheduled",
                value=f"<t:{self.target_timestamp}:F>",
            ),
            view=self,
        )

        scrims_channel = discord.utils.get(
            interaction.guild.text_channels if interaction.guild else [],
            name="scrims",
        )
        if scrims_channel is None:
            await interaction.followup.send(
                "The `scrims` channel does not exist on this server.",
                ephemeral=True,
            )
            return

        thread_name = f"{self.team_name} vs {accepting_team['team_name']}"
        scrim_thread = await scrims_channel.create_thread(
            name=thread_name[:100],
            type=discord.ChannelType.public_thread,
            auto_archive_duration=10080,
        )

        thread_embed = discord.Embed(
            title="Scrim Match",
            description=f"Scheduled for <t:{self.target_timestamp}:F>",
            color=discord.Color.green(),
        )
        thread_embed.add_field(
            name=f"{challenger_team.get('team_name', 'Challenger Team')} ({challenger_team.get('region', 'Unknown')})",
            value=f"Owner: <@{challenger_team.get('owner_id')}>\nMembers: "
            + (" ".join(f"<@{member_id}>" for member_id in challenger_team.get("members", [])) or "No accepted members"),
            inline=False,
        )
        thread_embed.add_field(
            name=f"{accepting_team.get('team_name', 'Opponent Team')} ({accepting_team.get('region', 'Unknown')})",
            value=f"Owner: <@{accepting_team.get('owner_id')}>\nMembers: "
            + (" ".join(f"<@{member_id}>" for member_id in accepting_team.get("members", [])) or "No accepted members"),
            inline=False,
        )

        thread_message = await scrim_thread.send(
            content=f"<@{self.owner_id}> <@{accepting_team['owner_id']}>",
            embed=thread_embed,
            allowed_mentions=discord.AllowedMentions(users=True),
            view=ScrimThreadView(self.owner_id, accepting_team["owner_id"]),
        )
        scrim_threads = [
            thread for thread in load_scrim_threads()
            if thread.get("thread_id") != scrim_thread.id
        ]
        scrim_threads.append(
            {
                "thread_id": scrim_thread.id,
                "message_id": thread_message.id,
                "owner_ids": [self.owner_id, accepting_team["owner_id"]],
            }
        )
        save_scrim_threads(scrim_threads)

    @discord.ui.button(label="Cancel Scrim", style=discord.ButtonStyle.danger, custom_id="cancel_scrim")
    async def cancel_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the creator of this scrim request can cancel it.",
                ephemeral=True,
            )
            return

        if self.cancelled:
            await interaction.response.send_message(
                "This scrim request has already been cancelled.",
                ephemeral=True,
            )
            return

        if self.accepted:
            await interaction.response.send_message(
                "This scrim has already been accepted and cannot be cancelled.",
                ephemeral=True,
            )
            return

        self.cancelled = True
        remove_scrim_request(interaction.guild.id, self.owner_id, self.target_timestamp)
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Scrim Cancelled",
                description=f"**{self.team_name}** cancelled this scrim request.",
                color=discord.Color.red(),
            ),
            view=self,
        )


class ScrimThreadView(discord.ui.View):
    def __init__(self, challenger_owner_id: int, opponent_owner_id: int):
        super().__init__(timeout=None)
        self.owner_ids = {challenger_owner_id, opponent_owner_id}

    @discord.ui.button(
        label="Close Scrim",
        style=discord.ButtonStyle.danger,
        custom_id="close_scrim_thread",
    )
    async def close_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.owner_ids:
            await interaction.response.send_message(
                "Only one of the two team owners can close this scrim.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This button can only be used inside the scrim thread.",
                ephemeral=True,
            )
            return

        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.edit(archived=True, locked=True)


class TeamInviteModal(discord.ui.Modal):
    def __init__(self, team_name: str, owner_id: int, region: str):
        super().__init__(title="Invite player to team")
        self.team_name = team_name
        self.owner_id = owner_id
        self.region = region

        self.player_input = discord.ui.TextInput(
            label="Player username or ID",
            placeholder="Player or 123456789012345678",
            required=True,
            min_length=1,
            max_length=100,
        )
        self.add_item(self.player_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw_value = self.player_input.value.strip()
        player_id = None

        if raw_value.startswith("<@") and raw_value.endswith(">"):
            value = raw_value[2:-1]
            if value.startswith("!"):
                value = value[1:]
            if value.isdigit():
                player_id = int(value)
        elif raw_value.isdigit():
            player_id = int(raw_value)
        else:
            member = discord.utils.find(
                lambda m: m.name.lower() == raw_value.lower()
                or m.display_name.lower() == raw_value.lower(),
                interaction.guild.members,
            )
            if member is not None:
                player_id = member.id

        if player_id is None:
            await interaction.response.send_message(
                "Could not find that player. Try a username or user ID.",
                ephemeral=True,
            )
            return

        if player_id == self.owner_id:
            await interaction.response.send_message(
                "You cannot invite yourself to your own team.",
                ephemeral=True,
            )
            return

        if get_team_for_player(player_id) is not None:
            await interaction.response.send_message(
                "That player is already on a team.",
                ephemeral=True,
            )
            return

        existing_requests = [
            request for request in load_team_requests()
            if request.get("player_id") == player_id and request.get("team_name") == self.team_name
        ]
        if existing_requests:
            await interaction.response.send_message(
                "That invite has already been sent.",
                ephemeral=True,
            )
            return

        requests = load_team_requests()
        requests.append(
            {
                "player_id": player_id,
                "team_name": self.team_name,
                "owner_id": self.owner_id,
                "region": self.region,
            }
        )
        save_team_requests(requests)

        await interaction.response.send_message(
            f"Invited <@{player_id}> to **{self.team_name}**.",
            allowed_mentions=discord.AllowedMentions(users=True),
            ephemeral=True,
        )


class TeamKickModal(discord.ui.Modal):
    def __init__(self, team_name: str, owner_id: int):
        super().__init__(title="Kick team member")
        self.team_name = team_name
        self.owner_id = owner_id

        self.member_input = discord.ui.TextInput(
            label="Member username or ID",
            placeholder="Member or 123456789012345678",
            required=True,
            min_length=1,
            max_length=100,
        )
        self.add_item(self.member_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw_value = self.member_input.value.strip()
        member_id = None
        
        if raw_value.isdigit():
            member_id = int(raw_value)
        else:
            member = discord.utils.find(
                lambda m: m.name.lower() == raw_value.lower()
                or m.display_name.lower() == raw_value.lower(),
                interaction.guild.members,
            )
            if member is not None:
                member_id = member.id

        if member_id is None:
            await interaction.response.send_message(
                "Could not find that member. Try a username or user ID.",
                ephemeral=True,
            )
            return

        teams = load_teams()
        team = next((t for t in teams if t.get("team_name") == self.team_name), None)
        if team is None:
            await interaction.response.send_message(
                f"Team **{self.team_name}** could not be found.",
                ephemeral=True,
            )
            return

        members = team.get("members", [])
        if member_id not in members:
            await interaction.response.send_message(
                "That player is not a member of this team.",
                ephemeral=True,
            )
            return

        members.remove(member_id)
        save_teams(teams)

        await interaction.response.send_message(
            f"Removed <@{member_id}> from **{self.team_name}**.",
            allowed_mentions=discord.AllowedMentions(users=True),
            ephemeral=True,
        )


class TeamNameModal(discord.ui.Modal):
    def __init__(self, owner_view: "TeamOwnerView", source_message: discord.Message | None):
        super().__init__(title="Edit team name")
        self.owner_view = owner_view
        self.source_message = source_message
        self.name_input = discord.ui.TextInput(
            label="Team name",
            default=owner_view.team_name,
            required=True,
            min_length=1,
            max_length=100,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name_input.value.strip()
        teams = load_teams()
        if team_name_exists(teams, new_name, self.owner_view.owner_id):
            await interaction.response.send_message(
                "A team with that name already exists.",
                ephemeral=True,
            )
            return

        team = next(
            (
                team for team in teams
                if team.get("owner_id") == self.owner_view.owner_id
                and team.get("team_name") == self.owner_view.team_name
            ),
            None,
        )
        if team is None:
            await interaction.response.send_message(
                "Your team could not be found.",
                ephemeral=True,
            )
            return

        old_name = team["team_name"]
        team["team_name"] = new_name
        save_teams(teams)

        requests = load_team_requests()
        for request in requests:
            if request.get("team_name") == old_name and request.get("owner_id") == self.owner_view.owner_id:
                request["team_name"] = new_name
        save_team_requests(requests)

        self.owner_view.team_name = new_name
        if self.source_message is not None:
            await self.source_message.edit(
                embed=team_embed(team, "Your Team"),
                view=self.owner_view,
            )

        await interaction.response.send_message(
            f"Team name changed to **{new_name}**.",
            ephemeral=True,
        )


class TeamRegionModal(discord.ui.Modal):
    def __init__(self, owner_view: "TeamOwnerView", source_message: discord.Message | None):
        super().__init__(title="Edit team region")
        self.owner_view = owner_view
        self.source_message = source_message
        self.region_input = discord.ui.TextInput(
            label="Region",
            placeholder="NA or EU",
            default=owner_view.region,
            required=True,
            min_length=2,
            max_length=2,
        )
        self.add_item(self.region_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_region = self.region_input.value.strip().upper()
        if new_region not in {"NA", "EU"}:
            await interaction.response.send_message(
                "Region must be either `NA` or `EU`.",
                ephemeral=True,
            )
            return

        teams = load_teams()
        team = next(
            (
                team for team in teams
                if team.get("owner_id") == self.owner_view.owner_id
                and team.get("team_name") == self.owner_view.team_name
            ),
            None,
        )
        if team is None:
            await interaction.response.send_message(
                "Your team could not be found.",
                ephemeral=True,
            )
            return

        team["region"] = new_region
        save_teams(teams)

        requests = load_team_requests()
        for request in requests:
            if request.get("team_name") == self.owner_view.team_name and request.get("owner_id") == self.owner_view.owner_id:
                request["region"] = new_region
        save_team_requests(requests)

        self.owner_view.region = new_region
        if self.source_message is not None:
            await self.source_message.edit(
                embed=team_embed(team, "Your Team"),
                view=self.owner_view,
            )

        await interaction.response.send_message(
            f"Team region changed to **{new_region}**.",
            ephemeral=True,
        )


class TeamScrimPicker(discord.ui.View):
    def __init__(self, team_name: str, owner_id: int, region: str):
        super().__init__(timeout=300)
        self.team_name = team_name
        self.owner_id = owner_id
        self.region = region

        self.hour_select = discord.ui.Select(
            placeholder="Select an hour",
            options=[
                discord.SelectOption(label=str(hour), value=str(hour))
                for hour in range(1, 13)
            ],
        )
        self.minute_select = discord.ui.Select(
            placeholder="Select minutes",
            options=[
                discord.SelectOption(label=f":{minute:02d}", value=str(minute))
                for minute in (0, 15, 30, 45)
            ],
        )
        self.period_select = discord.ui.Select(
            placeholder="Select AM or PM",
            options=[
                discord.SelectOption(label="AM", value="AM"),
                discord.SelectOption(label="PM", value="PM"),
            ],
        )
        self.add_item(self.hour_select)
        self.add_item(self.minute_select)
        self.add_item(self.period_select)
        self.hour_select.callback = self._select_time
        self.minute_select.callback = self._select_time
        self.period_select.callback = self._select_time

    async def _select_time(self, interaction: discord.Interaction):
        await interaction.response.defer()

    @discord.ui.button(label="Create Scrim Request", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can create this scrim request.",
                ephemeral=True,
            )
            return

        if not self.hour_select.values or not self.minute_select.values or not self.period_select.values:
            await interaction.response.send_message(
                "Please select an hour, minute, and AM/PM before continuing.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        hour = int(self.hour_select.values[0])
        minute = int(self.minute_select.values[0])
        period = self.period_select.values[0]
        if period == "PM" and hour != 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0

        est = timezone(timedelta(hours=-4), name="EST")
        now = datetime.now(est)
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_time <= now:
            target_time += timedelta(days=1)

        target_timestamp = int(target_time.timestamp())
        adaptive_time = f"<t:{target_timestamp}:F>"
        role_name = "NA Scrims" if self.region == "NA" else "EU Scrims"
        scrim_role = discord.utils.get(interaction.guild.roles, name=role_name)
        challenge_channel = discord.utils.get(interaction.guild.text_channels, name="scrims-requests")

        if challenge_channel is None:
            await interaction.followup.send(
                "The `scrims-requests` channel does not exist on this server.",
                ephemeral=True,
            )
            return

        if scrim_role is None:
            await interaction.followup.send(
                f"The `{role_name}` role does not exist on this server.",
                ephemeral=True,
            )
            return

        role_mention = scrim_role.mention
        request = {
            "guild_id": interaction.guild.id,
            "team_name": self.team_name,
            "owner_id": self.owner_id,
            "region": self.region,
            "target_timestamp": target_timestamp,
        }
        view = ScrimAcceptView(
            request["team_name"],
            request["owner_id"],
            request["region"],
            request["target_timestamp"],
        )
        challenge_message = await challenge_channel.send(
            embed=scrim_request_embed(request),
            view=view,
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )
        await challenge_channel.send(role_mention) #issue
        save_scrim_requests(
            [
                saved_request for saved_request in load_scrim_requests()
                if not (
                    saved_request.get("guild_id") == request["guild_id"]
                    and saved_request.get("owner_id") == request["owner_id"]
                    and saved_request.get("target_timestamp") == request["target_timestamp"]
                )
            ] + [request]
        )
        interaction.client.add_view(view, message_id=challenge_message.id)
        await interaction.followup.send(
            f"Scrim request sent to `scrims-requests` for **{self.team_name}** at {adaptive_time}.",
            ephemeral=True,
        )


class TeamOwnerView(discord.ui.View):
    def __init__(self, team_name: str, owner_id: int, region: str):
        super().__init__(timeout=None)
        self.team_name = team_name
        self.owner_id = owner_id
        self.region = region

    @discord.ui.button(label="Invite", style=discord.ButtonStyle.primary, custom_id="team_invite")
    async def invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can invite players.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TeamInviteModal(self.team_name, self.owner_id, self.region))

    @discord.ui.button(label="Scrim", style=discord.ButtonStyle.success, custom_id="team_scrim")
    async def scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can request a scrim.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Select the scrim time. Times are interpreted as EST.",
            view=TeamScrimPicker(self.team_name, self.owner_id, self.region),
            ephemeral=True,
        )

    @discord.ui.button(label="Edit Name", style=discord.ButtonStyle.secondary, custom_id="team_edit_name")
    async def edit_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can edit the team name.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TeamNameModal(self, interaction.message))

    @discord.ui.button(label="Edit Region", style=discord.ButtonStyle.secondary, custom_id="team_edit_region")
    async def edit_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can edit the team region.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TeamRegionModal(self, interaction.message))

    @discord.ui.button(label="Disband", style=discord.ButtonStyle.danger, custom_id="team_disband")
    async def disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can disband the team.",
                ephemeral=True,
            )
            return

        teams = load_teams()
        remaining = [team for team in teams if team.get("team_name") != self.team_name]
        save_teams(remaining)

        requests = load_team_requests()
        remaining_requests = [
            request for request in requests if request.get("team_name") != self.team_name
        ]
        save_team_requests(remaining_requests)

        await interaction.response.send_message(
            f"Team **{self.team_name}** has been disbanded.",
            ephemeral=True,
        )

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary, custom_id="team_kick")
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the team owner can kick members.",
                ephemeral=True,
            )
            return

        team = next((t for t in load_teams() if t.get("team_name") == self.team_name), None)
        if team is None:
            await interaction.response.send_message(
                f"Team **{self.team_name}** could not be found.",
                ephemeral=True,
            )
            return

        if not team.get("members"):
            await interaction.response.send_message(
                "This team has no members to kick.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TeamKickModal(self.team_name, self.owner_id))


class TeamMemberView(discord.ui.View):
    def __init__(self, team_name: str, owner_id: int):
        super().__init__(timeout=None)
        self.team_name = team_name
        self.owner_id = owner_id

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, custom_id="team_leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.owner_id:
            await interaction.response.send_message(
                "Only team members can leave the team. The owner must disband it.",
                ephemeral=True,
            )
            return

        teams = load_teams()
        team = next(
            (
                candidate for candidate in teams
                if candidate.get("team_name") == self.team_name
                and candidate.get("owner_id") == self.owner_id
            ),
            None,
        )
        if team is None or interaction.user.id not in team.get("members", []):
            await interaction.response.send_message(
                "You are no longer a member of this team.",
                ephemeral=True,
            )
            return

        team["members"].remove(interaction.user.id)
        save_teams(teams)

        await interaction.response.send_message(
            f"You left **{self.team_name}**.",
            ephemeral=True,
        )


class League(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.restoring_scrims = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self.restoring_scrims:
            return

        self.restoring_scrims = True
        try:
            active_threads = []
            for thread_record in load_scrim_threads():
                try:
                    thread = await self.bot.fetch_channel(thread_record["thread_id"])
                    await thread.fetch_message(thread_record["message_id"])
                except discord.NotFound:
                    continue
                except (discord.Forbidden, discord.HTTPException, KeyError):
                    active_threads.append(thread_record)
                    continue

                if not thread.archived and not thread.locked:
                    self.bot.add_view(
                        ScrimThreadView(*thread_record["owner_ids"]),
                        message_id=thread_record["message_id"],
                    )
                    active_threads.append(thread_record)

            save_scrim_threads(active_threads)

            saved_requests = load_scrim_requests()
            for guild in self.bot.guilds:
                challenge_channel = discord.utils.get(
                    guild.text_channels,
                    name="challenge-matches",
                )
                if challenge_channel is None:
                    continue

                guild_requests = [
                    request for request in saved_requests
                    if request.get("guild_id") == guild.id
                ]
                for request in guild_requests:
                    view = ScrimAcceptView(
                        request["team_name"],
                        request["owner_id"],
                        request["region"],
                        request["target_timestamp"],
                    )
                    scrim_role = discord.utils.get(
                        guild.roles,
                        name=f"{request['region']} Scrims",
                    )
                    message = await challenge_channel.send(
                        embed=scrim_request_embed(request),
                        view=view,
                        allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                    )
                    self.bot.add_view(view, message_id=message.id)
        finally:
            self.restoring_scrims = False

    @app_commands.command(name="create_team", description="Create a league team for NA or EU")
    @app_commands.describe(
        team_name="Your team's name",
        region="The region for your team",
        member1="Optional team member 1",
        member2="Optional team member 2",
        member3="Optional team member 3",
        member4="Optional team member 4",
        member5="Optional team member 5",
    )
    @app_commands.choices(
        region=[
            app_commands.Choice(name="NA", value="NA"),
            app_commands.Choice(name="EU", value="EU"),
        ]
    )
    async def create_team(
        self,
        interaction: discord.Interaction,
        team_name: str,
        region: app_commands.Choice[str],
        member1: discord.Member | None = None,
        member2: discord.Member | None = None,
        member3: discord.Member | None = None,
        member4: discord.Member | None = None,
        member5: discord.Member | None = None,
    ):
        team_name = team_name.strip()
        teams = load_teams()
        if team_name_exists(teams, team_name):
            await interaction.response.send_message(
                "A team with that name already exists.",
                ephemeral=True,
            )
            return

        if get_team_for_owner(interaction.user.id) is not None:
            await interaction.response.send_message(
                "You already have a registered team.",
                ephemeral=True,
            )
            return

        members = [member for member in (member1, member2, member3, member4, member5) if member is not None]
        if len(members) > 5:
            await interaction.response.send_message(
                "A team can have at most 5 members total, excluding the owner.",
                ephemeral=True,
            )
            return

        duplicate_member_ids = [member.id for member in members if member.id == interaction.user.id]
        if duplicate_member_ids:
            await interaction.response.send_message(
                "The team owner cannot also be listed as a member.",
                ephemeral=True,
            )
            return

        teams.append(
            {
                "owner_id": interaction.user.id,
                "team_name": team_name,
                "region": region.value,
                "members": [],
                "mmr": 0,
            }
        )
        save_teams(teams)

        if members:
            requests = load_team_requests()
            for member in members:
                requests.append(
                    {
                        "player_id": member.id,
                        "team_name": team_name,
                        "owner_id": interaction.user.id,
                        "region": region.value,
                    }
                )
            save_team_requests(requests)

        await interaction.response.send_message(
            f"Team **{team_name}** created in **{region.value}**. "
            f"{len(members)} join request(s) were saved to the team requests list.",
            ephemeral=True,
        )

    @app_commands.command(name="player", description="Show a player's MMR and team")
    @app_commands.describe(player_name="The player's username, display name, mention, or ID")
    async def player(self, interaction: discord.Interaction, player_name: str):
        raw_name = player_name.strip()
        player_id = int(raw_name) if raw_name.isdigit() else None

        if raw_name.startswith("<@") and raw_name.endswith(">"):
            mention_id = raw_name[2:-1].removeprefix("!")
            player_id = int(mention_id) if mention_id.isdigit() else None

        member = interaction.guild.get_member(player_id) if player_id is not None else None
        if member is None:
            member = discord.utils.find(
                lambda candidate: candidate.name.casefold() == raw_name.casefold()
                or candidate.display_name.casefold() == raw_name.casefold(),
                interaction.guild.members,
            )

        if member is None:
            await interaction.response.send_message(
                f"Could not find a player matching **{player_name}**.",
                ephemeral=True,
            )
            return

        rankings = load_rankings()
        team = get_team_for_player(member.id)
        team_text = team["team_name"] if team is not None else "No team"
        embed = discord.Embed(
            title=f"Player: {member.display_name}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="MMR", value=f"{rankings.get(member.id, 0):g}", inline=True)
        embed.add_field(name="Team", value=team_text, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="team_list", description="List league teams or show a team's members")
    @app_commands.describe(team_name="Optional team name to show its members")
    async def team_list(self, interaction: discord.Interaction, team_name: str | None = None):
        teams = load_teams()
        if not teams:
            await interaction.response.send_message("No teams have been created yet.", ephemeral=True)
            return

        if team_name is not None:
            team = next(
                (
                    candidate for candidate in teams
                    if candidate.get("team_name", "").casefold() == team_name.strip().casefold()
                ),
                None,
            )
            if team is None:
                await interaction.response.send_message(
                    f"No team named **{team_name}** was found.",
                    ephemeral=True,
                )
                return

            members = team.get("members", [])
            member_mentions = " ".join(f"<@{member_id}>" for member_id in members)
            embed = team_embed(team, "Team Members")
            embed.set_field_at(
                3,
                name="Members",
                value=member_mentions or "No accepted members",
                inline=False
            )
            await interaction.response.send_message(embed=embed,ephemeral=True)
            return

        team_lines = [
            f"**{team.get('team_name', 'Unknown Team')}** ({team.get('region', 'Unknown')})"
            for team in teams
        ]
        embed = discord.Embed(
            title="League Teams",
            description="\n".join(team_lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="team", description="View your team or accept a pending request")
    @app_commands.describe(team_name="The team name to accept if you want to join a team")
    async def team(self, interaction: discord.Interaction, team_name: str | None = None):
        current_team = get_team_for_player(interaction.user.id)
        if current_team is not None:
            if interaction.user.id == current_team["owner_id"]:
                view = TeamOwnerView(
                    current_team["team_name"],
                    interaction.user.id,
                    current_team["region"],
                )
            else:
                view = TeamMemberView(
                    current_team["team_name"],
                    current_team["owner_id"],
                )

            await interaction.response.send_message(
                embed=team_embed(current_team, "Your Team"),
                view=view,
                ephemeral=True,
            )
            return

        player_requests = get_requests_for_player(interaction.user.id)
        if not player_requests:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Team Requests",
                    description="You are not in a team and there are no pending requests for you.",
                    color=discord.Color.blurple(),
                ),
                ephemeral=True,
            )
            return

        if team_name is not None:
            matching_request = next(
                (
                    request for request in player_requests
                    if request.get("team_name", "").lower() == team_name.lower()
                ),
                None,
            )
            if matching_request is None:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Team Request Not Found",
                        description=f"There is no pending request for **{team_name}** for you.",
                        color=discord.Color.orange(),
                    ),
                    ephemeral=True,
                )
                return

            teams = load_teams()
            for team in teams:
                if team.get("team_name") != matching_request["team_name"]:
                    continue

                members = team.setdefault("members", [])
                if interaction.user.id in members:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Already a Team Member",
                            description="You are already a member of this team.",
                            color=discord.Color.orange(),
                        ),
                        ephemeral=True,
                    )
                    return

                if len(members) >= 5:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Team Full",
                            description="This team already has 6 members.",
                            color=discord.Color.red(),
                        ),
                        ephemeral=True,
                    )
                    return

                members.append(interaction.user.id)
                save_teams(teams)

                remaining_requests = [
                    request for request in load_team_requests()
                    if not (
                        request.get("player_id") == interaction.user.id
                        and request.get("team_name") == matching_request["team_name"]
                    )
                ]
                save_team_requests(remaining_requests)

                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Team Request Accepted",
                        description=f"You joined **{matching_request['team_name']}**.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Team Not Found",
                    description=f"The team **{team_name}** could not be found.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        request_list = "\n".join(
            f"**{request['team_name']}** ({request['region']})"
            for request in player_requests
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Pending Team Requests",
                description=(
                    f"{request_list}\n\n"
                    "Use `/team team_name:<Team Name>` to accept one of them."
                ),
                color=discord.Color.blurple(),
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(League(bot))

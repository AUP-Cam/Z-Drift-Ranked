import json
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

TEAMS_FILE = Path(__file__).resolve().parent.parent / "teams.txt"
TIME_SLOT_SECONDS = 15 * 60
TIME_SLOT_OPTIONS = 25
SCRIM_ROLE_NAMES = {
	"NA": "NA Scrims",
	"EU": "EU Scrims",
}


def next_time_slot():
	return int(time.time()) + TIME_SLOT_SECONDS


def adaptive_time(timestamp):
	return f"<t:{timestamp}:F>"


def relative_time_label(minutes):
	hours, remaining_minutes = divmod(minutes, 60)
	parts = []
	if hours:
		parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
	if remaining_minutes:
		parts.append(f"{remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}")
	return "in " + " ".join(parts)


def load_teams():
    try:
        return json.loads(TEAMS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_teams(teams):
    TEAMS_FILE.write_text(json.dumps(teams, indent=2), encoding="utf-8")


def get_team_for_owner(owner_id):
	return next(
		(team for team in load_teams() if team.get("owner_id") == owner_id),
		None,
	)


class ScrimView(discord.ui.View):
	def __init__(self, challenger_team, match_time):
		super().__init__(timeout=None)
		self.challenger_team = challenger_team
		self.match_time = int(match_time)
		self.accepted = False

	@discord.ui.button(
		label="Accept Scrim",
		style=discord.ButtonStyle.success,
		custom_id="accept_scrim",
	)
	async def accept_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
		if self.accepted:
			await interaction.response.send_message(
				"This scrim has already been accepted.",
				ephemeral=True,
			)
			return

		opposing_team = get_team_for_owner(interaction.user.id)
		if opposing_team is None:
			await interaction.response.send_message(
				"Only a team owner can accept a scrim.",
				ephemeral=True,
			)
			return
		if opposing_team["owner_id"] == self.challenger_team["owner_id"]:
			await interaction.response.send_message(
				"You cannot accept your own team's scrim.",
				ephemeral=True,
			)
			return

		self.accepted = True
		button.disabled = True
		await interaction.response.edit_message(
			content=(
				f"Scrim accepted: **{self.challenger_team['team_name']}** vs "
				f"**{opposing_team['team_name']}** at {adaptive_time(self.match_time)}."
			),
			view=self,
		)
		await interaction.channel.send(
			f"<@{self.challenger_team['owner_id']}> "
			f"<@{opposing_team['owner_id']}> your scrim has been created for "
			f"{adaptive_time(self.match_time)}."
		)


class Scrims(commands.Cog):
	def __init__(self, bot: commands.Bot):
		self.bot = bot

	@app_commands.command(name="create_team", description="Create a scrim team")
	@app_commands.describe(name="The name of your team", region="The team's region")
	@app_commands.choices(
		region=[
			app_commands.Choice(name="NA", value="NA"),
			app_commands.Choice(name="EU", value="EU"),
		]
	)
	async def create_team(
		self,
		interaction: discord.Interaction,
		name: str,
		region: app_commands.Choice[str],
	):
		teams = load_teams()
		teams.append(
			{
				"owner_id": interaction.user.id,
				"team_name": name,
				"area": region.value,
			}
		)
		save_teams(teams)

		await interaction.response.send_message(
			f"Team **{name}** created for {region.value}.",
			ephemeral=True,
		)

	@app_commands.command(name="delete_team", description="Remove your scrim team")
	async def delete_team(self, interaction: discord.Interaction):
		teams = load_teams()
		remaining_teams = [
			team for team in teams
			if team.get("owner_id") != interaction.user.id
		]

		if len(remaining_teams) == len(teams):
			await interaction.response.send_message(
				"You do not have a registered team.",
				ephemeral=True,
			)
			return

		save_teams(remaining_teams)
		await interaction.response.send_message(
			"Your team has been removed.",
			ephemeral=True,
		)

	@app_commands.command(name="scrim", description="Create an open scrim challenge")
	@app_commands.describe(time="When the scrim will be played")
	async def scrim(self, interaction: discord.Interaction, time: str):
		if interaction.channel is None or interaction.channel.name.lower() != "challenge-matches":
			await interaction.response.send_message(
				"The `/scrim` command can only be used in #challenge-matches.",
				ephemeral=True,
			)
			return

		try:
			match_time = int(time)
		except ValueError:
			await interaction.response.send_message(
				"Please choose a time from the autocomplete menu.",
				ephemeral=True,
			)
			return

		if match_time < next_time_slot():
			await interaction.response.send_message(
				"That time has passed. Please choose a new time from the menu.",
				ephemeral=True,
			)
			return

		team = get_team_for_owner(interaction.user.id)
		if team is None:
			await interaction.response.send_message(
				"You must create a team before creating a scrim.",
				ephemeral=True,
			)
			return

		role_name = SCRIM_ROLE_NAMES.get(team.get("area"))
		scrim_role = discord.utils.get(
			interaction.guild.roles if interaction.guild else [],
			name=role_name,
		)
		role_mention = f"{scrim_role.mention} " if scrim_role else ""

		await interaction.response.send_message(
			f"{role_mention}Scrim challenge from **{team['team_name']}** ({team['area']}) at "
			f"{adaptive_time(match_time)}. "
			"Another team owner can accept this challenge.",
			view=ScrimView(team, match_time),
			allowed_mentions=discord.AllowedMentions(roles=True),
		)

	@scrim.autocomplete("time")
	async def scrim_time_autocomplete(
		self,
		interaction: discord.Interaction,
		current: str,
	) -> list[app_commands.Choice[str]]:
		start = next_time_slot()
		choices = []
		for offset in range(TIME_SLOT_OPTIONS):
			timestamp = start + (offset * TIME_SLOT_SECONDS)
			minutes = (offset + 1) * 15
			choice = app_commands.Choice(
				name=relative_time_label(minutes),
				value=str(timestamp),
			)
			if not current or current.lower() in choice.name.lower():
				choices.append(choice)
		return choices[:25]


async def setup(bot: commands.Bot):
	await bot.add_cog(Scrims(bot))


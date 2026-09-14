import discord
import asyncio
import os
import subprocess
import sys
from discord import app_commands
from discord.ext import commands

from database import add_ban, get_bans, initialize_database, remove_ban, get_json

OWNER_ID = 584539388747448321
RANKED_ROLE_NAMES = {
	"NA": "NA Ranked",
	"EU": "EU Ranked",
}
SCRIM_ROLE_NAMES = {
	"NA": "NA Scrims",
	"EU": "EU Scrims",
}
ROLE_NAMES = (
	"NA Ranked",
	"NA Scrims",
	"EU Ranked",
	"EU Scrims",
)
REPORT_VIOLATIONS = [
	"dodging",
	"dribbling",
	"insta-breaking",
	"jokr-training",
	"mis-voting",
	"toxicity",
	"greifing",
]


class ReportActionView(discord.ui.View):
	def __init__(self, reported_user: discord.Member, reporter: discord.Member):
		super().__init__(timeout=None)
		self.reported_user = reported_user
		self.reporter = reporter

	def _is_admin(self, interaction: discord.Interaction) -> bool:
		admin_role = (
			discord.utils.get(interaction.guild.roles, name="Admin")
			or discord.utils.get(interaction.guild.roles, name="Admins")
			or discord.utils.get(interaction.guild.roles, name="admin")
		)
		return admin_role is not None and admin_role in interaction.user.roles

	def _save_ban(self, user_id: int):
		add_ban(user_id)

	@discord.ui.button(label="Ban Reported User", style=discord.ButtonStyle.danger, custom_id="ban_reported_user")
	async def ban_reported_user(self, interaction: discord.Interaction, button: discord.ui.Button):
		if not self._is_admin(interaction):
			await interaction.response.send_message("Only admins can ban users.", ephemeral=True)
			return
		self._save_ban(self.reported_user.id)
		await interaction.response.send_message(
			f"Banned reported user: {self.reported_user.mention}",
			ephemeral=True,
		)

	@discord.ui.button(label="Ban Reporter", style=discord.ButtonStyle.danger, custom_id="ban_reporter")
	async def ban_reporter(self, interaction: discord.Interaction, button: discord.ui.Button):
		if not self._is_admin(interaction):
			await interaction.response.send_message("Only admins can ban users.", ephemeral=True)
			return
		self._save_ban(self.reporter.id)
		await interaction.response.send_message(
			f"Banned reporter: {self.reporter.mention}",
			ephemeral=True,
		)

	@discord.ui.button(label="Delete Report", style=discord.ButtonStyle.secondary, custom_id="delete_report")
	async def delete_report(self, interaction: discord.Interaction, button: discord.ui.Button):
		if not self._is_admin(interaction):
			await interaction.response.send_message("Only admins can delete reports.", ephemeral=True)
			return
		await interaction.message.delete()
		await interaction.response.send_message("Report deleted.", ephemeral=True)


class RoleView(discord.ui.View):
	def __init__(self):
		super().__init__(timeout=None)

	async def toggle_role(self, interaction: discord.Interaction, role_name: str):
		role = discord.utils.get(interaction.guild.roles, name=role_name)
		if role is None:
			await interaction.response.send_message(
				f"The `{role_name}` role does not exist on this server.",
				ephemeral=True,
			)
			return

		if role in interaction.user.roles:
			await interaction.user.remove_roles(role)
			message = f"Removed **@{role_name}** from you."
		else:
			await interaction.user.add_roles(role)
			message = f"Added **@{role_name}** to you."

		await interaction.response.send_message(message, ephemeral=True)

	@discord.ui.button(label="@NA Ranked", style=discord.ButtonStyle.primary, custom_id="role_na_ranked")
	async def na_ranked(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.toggle_role(interaction, "NA Ranked")

	@discord.ui.button(label="@NA Scrims", style=discord.ButtonStyle.primary, custom_id="role_na_scrims")
	async def na_scrims(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.toggle_role(interaction, "NA Scrims")

	@discord.ui.button(label="@EU Ranked", style=discord.ButtonStyle.primary, custom_id="role_eu_ranked")
	async def eu_ranked(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.toggle_role(interaction, "EU Ranked")

	@discord.ui.button(label="@EU Scrims", style=discord.ButtonStyle.primary, custom_id="role_eu_scrims")
	async def eu_scrims(self, interaction: discord.Interaction, button: discord.ui.Button):
		await self.toggle_role(interaction, "EU Scrims")


class General(commands.Cog):
	def __init__(self, bot: commands.Bot):
		self.bot = bot
		self.ranked_ping_last_used = 0

	async def _clear_disable_channels(self, guild: discord.Guild):
		queue_channel = discord.utils.get(
			guild.text_channels,
			name="zdrift-queue",
		)
		challenge_channel = discord.utils.get(
			guild.text_channels,
			name="scrims-requests",
		)
		queue_message = "The `zdrift-queue` channel was not found."
		challenge_message = "The `scrims-requests` channel was not found."

		if queue_channel is not None:
			try:
				deleted_messages = await queue_channel.purge(limit=None)
				queue_message = f"Removed {len(deleted_messages)} messages from `zdrift-queue`."
			except discord.Forbidden:
				queue_message = "I do not have permission to remove messages from `zdrift-queue`."

		if challenge_channel is not None:
			try:
				deleted_messages = await challenge_channel.purge(limit=None)
				challenge_message = f"Removed {len(deleted_messages)} messages from `scrims-requests`."
			except discord.Forbidden:
				challenge_message = "I do not have permission to remove messages from `scrims-requests`."

		return queue_message, challenge_message

	async def _restart_process(self):
		await asyncio.sleep(1)
		bot_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bot.py"))
		subprocess.Popen(
			[sys.executable, bot_path],
			cwd=os.path.dirname(bot_path),
		)
		os._exit(0)

	@app_commands.command(name="reaction_roles", description="Post the region and game-mode role selector")
	async def reaction_roles(self, interaction: discord.Interaction):
		if interaction.user.id != OWNER_ID:
			await interaction.response.send_message(
				"You are not authorized to post the role selector.",
				ephemeral=True,
			)
			return

		missing_roles = [
			role_name
			for role_name in ROLE_NAMES
			if discord.utils.get(interaction.guild.roles, name=role_name) is None
		]
		if missing_roles:
			await interaction.response.send_message(
				"Create these roles first: " + ", ".join(missing_roles),
				ephemeral=True,
			)
			return

		await interaction.response.send_message(
			"Select the roles you want. Press a button again to remove a role.",
			view=RoleView(),
		)

	@app_commands.command(name="ranked_ping", description="Ping a regional scrim role")
	@app_commands.choices(
		region=[
			app_commands.Choice(name="NA", value="NA"),
			app_commands.Choice(name="EU", value="EU"),
		]
	)
	async def ranked_ping(self, interaction: discord.Interaction, region: app_commands.Choice[str]):
		cooldown_seconds = 30 * 60
		now = discord.utils.utcnow().timestamp()
		if now - self.ranked_ping_last_used < cooldown_seconds:
			remaining = int(cooldown_seconds - (now - self.ranked_ping_last_used))
			minutes, seconds = divmod(remaining, 60)
			await interaction.response.send_message(
				f"This command is on a cooldown. Try again in {minutes}m {seconds}s.",
				ephemeral=True,
			)
			return

		self.ranked_ping_last_used = now

		role_name = RANKED_ROLE_NAMES[region.value]
		role = discord.utils.get(
			interaction.guild.roles if interaction.guild else [],
			name=role_name,
		)
		if role is None:
			await interaction.response.send_message(
				f"The `{role_name}` role does not exist on this server.",
				ephemeral=True,
			)
			return
		queue = get_json("current_queue", [])
		queue_size = len(queue)
		await interaction.response.send_message(f"{queue_size}/8 in queue: {role.mention}",
			allowed_mentions=discord.AllowedMentions(roles=True),
		)

	@app_commands.command(name="report", description="Report a player for a rule violation")
	@app_commands.describe(user="The player to report", violation="The violation category")
	@app_commands.choices(
		violation=[
			app_commands.Choice(name=violation, value=violation)
			for violation in REPORT_VIOLATIONS
		]
	)
	async def report(
		self,
		interaction: discord.Interaction,
		user: discord.Member,
		violation: app_commands.Choice[str],
	):
		if interaction.guild is None:
			await interaction.response.send_message(
				"This command can only be used in a server.",
				ephemeral=True,
			)
			return

		report_channel = discord.utils.get(interaction.guild.text_channels, name="reports")
		admin_role = (
			discord.utils.get(interaction.guild.roles, name="Admin")
			or discord.utils.get(interaction.guild.roles, name="Admins")
			or discord.utils.get(interaction.guild.roles, name="admin")
		)

		if report_channel is None:
			await interaction.response.send_message(
				"The `reports` channel does not exist on this server.",
				ephemeral=True,
			)
			return

		if admin_role is None:
			await interaction.response.send_message(
				"The admin role was not found on this server.",
				ephemeral=True,
			)
			return

		report_message = (
			f"{admin_role.mention} New report submitted:\n"
			f"Reported user: {user.mention}\n"
			f"Reported by: {interaction.user.mention}\n"
			f"Violation: **{violation.value}**"
		)
		await report_channel.send(
			report_message,
			view=ReportActionView(user, interaction.user),
			allowed_mentions=discord.AllowedMentions(roles=True, users=True),
		)
		await interaction.response.send_message(
			"Your report has been submitted to the reports channel.",
			ephemeral=True,
		)

	@app_commands.command(name="toggle_ban", description="Ban or unban a player")
	@app_commands.describe(player="The player to ban or unban")
	async def toggle_ban(self, interaction: discord.Interaction, player: discord.Member):
		admin_role = (
			discord.utils.get(interaction.guild.roles, name="Admin")
			or discord.utils.get(interaction.guild.roles, name="Admins")
			or discord.utils.get(interaction.guild.roles, name="admin")
		)
		if admin_role is None or admin_role not in interaction.user.roles:
			await interaction.response.send_message(
				"Only admins can ban or unban players.",
				ephemeral=True,
			)
			return

		banned_ids = get_bans()
		if str(player.id) in banned_ids:
			remove_ban(player.id)
			message = f"Unbanned {player.mention}."
		else:
			add_ban(player.id)
			message = f"Banned {player.mention}."

		await interaction.response.send_message(
			message,
			allowed_mentions=discord.AllowedMentions(users=True),
			ephemeral=True,
		)

	@app_commands.command(name="disable", description="Turn off the bot")
	async def disable(self, interaction: discord.Interaction):
		admin_role = (
			discord.utils.get(interaction.guild.roles, name="Admin")
			or discord.utils.get(interaction.guild.roles, name="Admins")
			or discord.utils.get(interaction.guild.roles, name="admin")
		)
		if admin_role is None or admin_role not in interaction.user.roles:
			await interaction.response.send_message(
				"Only admins can disable the bot.",
				ephemeral=True,
			)
			return

		await interaction.response.defer(ephemeral=True)
		queue_message, challenge_message = await self._clear_disable_channels(interaction.guild)

		await interaction.followup.send(
			f"{queue_message}\n"
			f"{challenge_message}\n"
			"Disabling the bot."
		)

		await self.bot.close()

	@app_commands.command(name="reload", description="Restart the bot and restore saved data")
	async def reload(self, interaction: discord.Interaction):
		admin_role = (
			discord.utils.get(interaction.guild.roles, name="Admin")
			or discord.utils.get(interaction.guild.roles, name="Admins")
			or discord.utils.get(interaction.guild.roles, name="admin")
		)
		if admin_role is None or admin_role not in interaction.user.roles:
			await interaction.response.send_message(
				"Only admins can reload the bot.",
				ephemeral=True,
			)
			return

		await interaction.response.defer(ephemeral=True)
		queue_message, challenge_message = await self._clear_disable_channels(interaction.guild)
		await interaction.followup.send(
			f"{queue_message}\n"
			f"{challenge_message}\n"
			"Restarting the bot now."
		)
		asyncio.create_task(self._restart_process())


async def setup(bot: commands.Bot):
	initialize_database()
	await bot.add_cog(General(bot))
	bot.add_view(RoleView())

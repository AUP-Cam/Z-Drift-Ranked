import discord  
from discord.ext import commands  
from discord import app_commands
import asyncio
import getpass
import os

bot: commands.bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
                print(f'Error syncing commands: {e}')
    print(f'Logged in as {bot.user.name}')
    
async def load_extensions():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')
            print(f'Loaded extension: {filename[:-3]}')
    
async def main():
    async with bot:
        await load_extensions()
        token = getpass.getpass('Enter the Discord bot token: ').strip()
        if not token:
            raise ValueError('A Discord bot token is required to start the bot.')
        await bot.start(token)
        
asyncio.run(main())


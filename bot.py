import discord  
from discord.ext import commands  
from discord import app_commands
import asyncio
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
        await bot.start('MTU0NjM1NDEyNTE0OTU3NzMwNw.Gkcyz8.1JyPt9DQlRBtluEMMuvBCkIwPMSCbGrWn0VJCI')
        
asyncio.run(main())


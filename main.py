import asyncio
from datetime import datetime, timedelta
import secrets
import time
import aiohttp
from discord.ext import commands, tasks
import discord
from discord import app_commands
import os
import mysql.connector
from mysql.connector import Error
import requests
import json
import base64
from flask import Flask, abort, jsonify, render_template, request, render_template_string, send_from_directory, flash, redirect, url_for, session
from dotenv import load_dotenv
import logging
from discord.ui import Button, View
from flask_mail import Mail, Message
from authlib.integrations.flask_client import OAuth
from flask_caching import Cache
import threading

load_dotenv()

# Configure logging
log_file = './logs/paypal.log'
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(log_file),
                        logging.StreamHandler()
                    ])

# Initialize bot
intents = discord.Intents.all()
prefix = "."
bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)
token = os.getenv('token')
reminders = {}
owner_id = 969809822176411649
end_time = datetime.now() + timedelta(minutes=1)

# Database configuration
db_config = {
    'user': 'inferno',
    'password': 'root',
    'host': 'localhost',
    'database': 'atlas_database',
    'charset': 'utf8mb4'
}

# PayPal configuration
paypal_client_id = os.getenv('paypal_client_id')
paypal_secret = os.getenv('paypal_secret')
paypal_api_base = 'https://api.paypal.com'

# OpenWeather configuration
weather_key = os.getenv('weather_key')

class CommandApprovalView(View):
    def __init__(self, user_id: int, name: str, description: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.name = name
        self.description = description

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green)
    async def approve_button_callback(self, interaction: discord.Interaction, button: Button):
        await self.handle_approval(interaction, approved=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
    async def deny_button_callback(self, interaction: discord.Interaction, button: Button):
        await self.handle_approval(interaction, approved=False)

    async def handle_approval(self, interaction: discord.Interaction, approved: bool):
        user = await bot.fetch_user(self.user_id)
        if approved:
            await user.send(embed=self.get_response_embed(f"{interaction.user} has approved your request for a custom command. You will be notifed when your command is ready"))
            await interaction.response.send_message("You have approved the custom command request.", ephemeral=True)
        else:
            await user.send(embed=self.get_response_embed(f"Your request for a custom command has been denied by {interaction.user}."))
            await interaction.response.send_message("You have denied the custom command request.", ephemeral=True)
    
    def get_response_embed(self, message: str):
        return discord.Embed(description=message, color=discord.Color.green() if "approved" in message else discord.Color.red())

class TicketView(View):
    def __init__(self, ticket_channel, creator_id):
        super().__init__(timeout=None)
        self.ticket_channel = ticket_channel
        self.creator_id = creator_id

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red)
    async def close_ticket_button_callback(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Closing Ticket...", ephemeral=True)
        await self.close_ticket_process(interaction.user)

    async def close_ticket_process(self, closer_user):
        messages = []
        users_info = {}
        async for message in self.ticket_channel.history(limit=None):
            if message.author.id not in users_info:
                member = await self.ticket_channel.guild.fetch_member(message.author.id)
                users_info[message.author.id] = {
                    'id': member.id,
                    'display_name': member.display_name,
                    'avatar_url': member.avatar.url,
                    'joined_at': member.joined_at,
                    'message_count': 0
                }
            users_info[message.author.id]['message_count'] += 1

            attachments = [{'url': att.url} for att in message.attachments]
            messages.append({
                'author_id': message.author.id,
                'content': message.content,
                'attachments': attachments
            })

        html_transcript = generate_html_transcript(messages, users_info)
        ticket_number = len([name for name in os.listdir('transcripts') if os.path.isfile(os.path.join('transcripts', name)) and name.startswith('general-')]) + 1
        transcript_path = f'transcripts/general-{ticket_number}.html'
        os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
        
        with open(transcript_path, 'w') as file:
            file.write(html_transcript)

        # Notify the user who closed the ticket
        try:
            embed = discord.Embed(title="Ticket Closed", description="The ticket has been closed. Here is the transcript.", color=discord.Color.green())
            embed.add_field(name="Transcript", value=f"http://picked-next-horse.ngrok-free.app/transcripts/general-{ticket_number}.html")
            await closer_user.send(embed=embed)
        except discord.Forbidden:
            logging.error(f"Could not DM {closer_user}.")

        # Notify the user who created the ticket
        creator = await bot.fetch_user(self.creator_id)
        try:
            embed = discord.Embed(title="Ticket Closed", description="The ticket you created has been closed. Here is the transcript.", color=discord.Color.green())
            embed.add_field(name="Transcript", value=f"http://picked-next-horse.ngrok-free.app/transcripts/general-{ticket_number}.html")
            await creator.send(embed=embed)
            await creator.send(content='**Please check <#1275271775810490510> For your ticket id if you ever need your ticket transcript please right it down**')
        except discord.Forbidden:
            logging.error(f"Could not DM {creator}.")

        await self.ticket_channel.send("Closing Ticket...")
        time.sleep(3)
        await self.ticket_channel.delete()


def get_db_connection():
    return mysql.connector.connect(**db_config)

def generate_html_transcript(messages, users_info):
    current_time = discord.utils.utcnow().strftime('%d %B %Y at %H:%M:%S (UTC)')
    html_content = f"""
    <html>
    <head>
        <title>Ticket Transcript</title>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #2c2f33; color: #ffffff; }}
            .message {{ border-bottom: 1px solid #444; padding: 10px; display: flex; align-items: center; }}
            .header, .footer {{ background-color: #23272a; padding: 10px; text-align: center; }}
            .user-info {{ display: none; position: absolute; background-color: #444; padding: 10px; border: 1px solid #555; }}
            .user:hover .user-info {{ display: block; }}
            .user-pfp {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 10px; }}
            .user {{ display: flex; align-items: center; cursor: pointer; }}
            .message-content {{ margin-left: 10px; }}
            .message-images img {{ max-width: 200px; max-height: 200px; margin: 5px; }}
        </style>
        <script defer src="/transcripts/cdn/ticket-obs/js/ticket.min.bundle.tim.js"></script>
    </head>
    <body>
        <div class='header'>
            <h1>Ticket Transcript</h1>
            <p class="timer">This ticket will be deleted in <span class="time-left"></span></p>
            <p>This transcript was generated on {current_time}</p>
            <script src="/transcripts/ticket.min.bundle.js"></script>
        </div>
    """

    for message in messages:
        user_info = users_info[message['author_id']]
        html_content += f"""
        <div class='message'>
            <img src='{user_info['avatar_url']}' class='user-pfp' />
            <p>{message['content']}</p>
            <div class='message-content'>
                <strong class='user'>{user_info['display_name']}
                    <div class='user-info'>
                        <p><strong>Member Since:</strong> {user_info['joined_at'].strftime('%b %d, %Y')}</p>
                        <p><strong>Member ID:</strong> {user_info['id']}</p>
                        <p><strong>Message Count:</strong> {user_info['message_count']}</p>
                    </div>
                </strong>
                <div class='message-images'>
        """

        for attachment in message['attachments']:
            if attachment['url']:
                html_content += f"<img src='{attachment['url']}' alt='attachment' />"

        html_content += "</div></div></div>"
    
    html_content += "<div class='footer'><p>End of transcript</p></div></body></html>"
    return html_content

async def create_ticket_channel(guild, category_id, channel_name, creator):
    category = discord.utils.get(guild.categories, id=category_id)
    if category:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            creator: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        return channel
    return None

def create_paypal_order(user_id):
    auth = (paypal_client_id, paypal_secret)
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    data = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {
                "currency_code": "EUR",
                "value": "9.99"  # Premium price
            },
            "custom_id": str(user_id)
        }],
        "application_context": {
            "return_url": "http://picked-next-horse.ngrok-free.app/",
            "cancel_url": "http://picked-next-horse.ngrok-free.app/"
        }
    }
    response = requests.post(f'{paypal_api_base}/v2/checkout/orders', auth=auth, headers=headers, json=data)

    logging.info(f"PayPal Order Creation Response Status: {response.status_code}")
    logging.info(f"PayPal Order Creation Response Content: {response.text}")

    if response.status_code == 201:  # Created
        response_json = response.json()
        if 'links' in response_json:
            approval_url = next(link['href'] for link in response_json['links'] if link['rel'] == 'approve')
            return approval_url
        else:
            raise KeyError('links key not found in PayPal API response')
    else:
        response.raise_for_status()

def get_paypal_access_token():
    client_id = os.getenv('PAYPAL_CLIENT_ID')
    client_secret = os.getenv('PAYPAL_SECRET')
    auth = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
    headers = {
        'Authorization': f'Basic {auth}',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    data = {'grant_type': 'client_credentials'}

    response = requests.post('https://api.paypal.com/v1/oauth2/token', headers=headers, data=data)

    if response.status_code == 200:
        return response.json().get('access_token')
    else:
        logging.error(f"Error retrieving access token: {response.text}")
        return None

def check_payment_status(order_id):
    access_token = get_paypal_access_token()
    if not access_token:
        return {"status": "FAILED", "message": "Access token retrieval failed"}

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    url = f'https://api.paypal.com/v2/checkout/orders/{order_id}'

    response = requests.get(url, headers=headers)

    logging.info(f"Check Payment Status Response Status: {response.status_code}")
    logging.info(f"Check Payment Status Response Content: {response.text}")

    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Error checking payment status: {response.text}")
        return {"status": "FAILED", "message": "Payment status check failed"}

def capture_paypal_order(order_id):
    auth = (paypal_client_id, paypal_secret)
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    response = requests.post(
        f'{paypal_api_base}/v2/checkout/orders/{order_id}/capture',
        auth=auth, headers=headers
    )

    logging.info(f"Capture PayPal Order Response Status: {response.status_code}")
    logging.info(f"Capture PayPal Order Response Content: {response.text}")

    response_json = response.json()

    if response.status_code == 201:  # Created
        return response_json
    else:
        response.raise_for_status()

async def remind_user(user_id: int, remind_time_at: datetime, message: str):
    await asyncio.sleep((remind_time_at - discord.utils.utcnow()).total_seconds())

    if user_id in reminders:
        user_reminders = reminders[user_id]
        for reminder in user_reminders:
            if reminder["remind_time_at"] == remind_time_at:
                user = await bot.fetch_user(user_id)
                embed = discord.Embed(
                    title='Reminder',
                    description='**You have a reminder**',
                    color=discord.Color.blue()
                )
                embed.add_field(name="Reminder", value=message, inline=False)
                embed.set_footer(text=f"! Skye")
                await user.send(embed=embed)
                reminders[user_id].remove(reminder)
                break


@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.CustomActivity(name="Watching Dev"), status="dnd")

    guild_count = 0
    for guild in bot.guilds:
        print(f"Guild ID: {guild.id} (name: {guild.name})")
        guild_count += 1

    print(f"Logged in as {bot.user} | Servers: {guild_count}")

    try:
        synced_commands = await bot.tree.sync()
        print(f"Synced {len(synced_commands)} Commands")
    except Exception as e:
        logging.error(f"An error with syncing application commands has occurred: {e}")

@bot.event
async def on_shutdown():
    global reminders
    reminders = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    user_id = message.author.id
    try:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            cursor.execute("SELECT afk_message FROM afk_status WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            if result:
                afk_message = result[0]
                await message.channel.send(f"Welcome back {message.author.mention} Your no longer AFK", delete_after=5)
                cursor.execute("DELETE FROM afk_status WHERE user_id = %s", (user_id,))
                connection.commit()
            cursor.close()
            connection.close()
    except Error as e:
        logging.error(f"Error: {e}")

    await bot.process_commands(message)

@bot.tree.command(name="hello", description="Says hello back")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello {interaction.user.mention}", ephemeral=True)

@bot.tree.command(name="ping", description="Returns the bot's ping in ms")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Latency: {latency}ms", ephemeral=True)

@bot.tree.command(name="buy-premium", description="Buy premium access")
async def buy_premium(interaction: discord.Interaction):
    try:
        approval_url = create_paypal_order(interaction.user.id)
        await interaction.response.send_message(f"Click [here]({approval_url}) to complete your purchase.", ephemeral=True)
    except KeyError as e:
        await interaction.response.send_message("There was an error processing your payment. Please try again later.", ephemeral=True)
        logging.error(f"Error: {e}")
    except requests.RequestException as e:
        await interaction.response.send_message("There was a problem connecting to the payment service. Please try again later.", ephemeral=True)
        logging.error(f"Request Error: {e}")

@bot.tree.command(name="premium-check", description="Check if you have premium")
async def premium(interaction: discord.Interaction):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM premium_users WHERE id = %s", (interaction.user.id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        await interaction.response.send_message("You have premium", ephemeral=True)
    else:
        await interaction.response.send_message("You do not have premium", ephemeral=True)


@bot.tree.command(name="create_role", description="Allows a premium member to create a role with no perms")
async def create_role(interaction: discord.Interaction, role_name: str, color: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM premium_users WHERE id = %s", (interaction.user.id,))
    result = cursor.fetchone()
    conn.close

    if result:
        try:
            color_value = int(color.strip('#'), 16)
            guild = interaction.guild
            user_role = await guild.create_role(name=role_name, color=discord.Color(color_value))
            await interaction.user.add_roles(user_role)
            await interaction.response.send_message(f"Created role: {role_name} (Color: #{color}), Added role: {role_name} to you", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invaild color format. Please use a hexadecimal color code, e.g., #ff5733", ephemeral=True)
        except discord.DiscordException as e:
            await interaction.response.send_message(f"An error occurred while creating the role: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("You do not have premium therefor you cant run this command to get premium run `/but-premium` FYI its 9,99 EUR", ephemeral=True)

@bot.tree.command(name="custom-command", description="Request a custom command")
async def custom_command(interaction: discord.Interaction, name: str, description: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count FROM command_requests WHERE user_id = %s", (interaction.user.id,))
    result = cursor.fetchone()

    if result and result[0] >= 2:
        await interaction.response.send_message("You have reached the maximum number of custom command requests make a ticket [here](https://discord.gg/UzMYzCs2Ge) or reach out to inferno to request more", ephemeral=True)
        return

    cursor.execute("INSERT INTO command_requests (user_id, count) VALUES (%s, 1) ON DUPLICATE KEY UPDATE count = count + 1", (interaction.user.id,))
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="Custom Command Request",
        description=f"**User:** {interaction.user}\n**Command Name:** {name}\n**Description:** {description}",
        color=discord.Color.blue()
    )

    view = CommandApprovalView(interaction.user.id, name, description)

    owner = await bot.fetch_user(owner_id)
    await owner.send(embed=embed, view=view)
    await interaction.response.send_message("Your custom command request has been sent for approval.", ephemeral=True)

@bot.tree.command(name="notify", description="Notify the user when their command is done")
async def notify(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != owner_id:
        await interaction.response.send_message("You are not authorized to use this command")
        return

    try:
        user = await bot.fetch_user(user.id)
        embed = discord.Embed(
            title="Custom Command Ready",
            description=f"Your custom command is now ready and available for use. | Sent by: <@{interaction.user.id}> (ID: {interaction.user.id})",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Requested by {interaction.user}")

        await user.send(embed=embed)
        await interaction.response.send_message(f"Notification sent to user {user.mention}", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message(f"User {user.mention} not found", ephemeral=True)

@bot.tree.command(name='ticket-create', description="Create a new support ticket")
async def ticket(interaction: discord.Interaction):
    guild = interaction.guild
    category_id = 1269223300727443600
    category = discord.utils.get(guild.categories, id=category_id)

    if category:
        existing_tickets = [ch for ch in category.channels if ch.name.startswith('general-') or ch.name.startswith('service-')]
        ticket_number = len(existing_tickets) + 1
        ticket_name = f"general-{ticket_number}"

        channel = await create_ticket_channel(guild, category_id, ticket_name, interaction.user)

        if channel:
            await channel.send(
                embed=discord.Embed(title="New Ticket", description=f"Thank you <@{interaction.user.id}> for making a ticket our support team will be with you soon please describe the issue or having or what you need", color=discord.Color.blue()),
                view=TicketView(channel, interaction.user.id)
            )
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("Failed to create the ticket channel", ephemeral=True)

@bot.tree.command(name="cat", description="Gets a random cat image")
async def cat(interaction: discord.Interaction):
    response = requests.get("https://api.thecatapi.com/v1/images/search")
    if response.status_code == 200:
        data = response.json()
        if data:
            cat_image_url = data[0]["url"]
            embed = discord.Embed(title="Random Cat Image", color=discord.Color.blue())
            embed.set_image(url=cat_image_url)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Could not retrive a cat image at the moment")
    else:
        await interaction.response.send_message("Failed to fetch a cat image")

@bot.tree.command(name="weather", description="Gets the weather for a certin location")
@app_commands.describe(location="The location to search")
async def Weather(interaction: discord.Interaction, location: str):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={weather_key}&units=metric"

    try:
        response = requests.get(url)
        data = response.json()

        if response.status_code == 200:
            city_name = data['name']
            weather_description = data['weather'][0]['description']
            tempatrue = data['main']['temp']
            humidity = data['main']['humidity']
            icon_code = data['weather'][0]['icon']

            emoji_dict = {
                'clear sky': '☀️',
                'few clouds': '🌤️',
                'scattered clouds': '⛅',
                'broken clouds': '☁️',
                'overcast clouds': ':cloud:',
                'shower rain': '🌦️',
                'light rain': '🌦️',
                'rain': '🌧️',
                'thunderstorm': '⛈️',
                'snow': '🌨️',
                'mist': '🌫️'
            }

            weather_main = weather_description.lower()
            unicode_char = emoji_dict.get(weather_main, '\u1F30D')

            embed = discord.Embed(
                title=f"Weather in {city_name}",
                description=f"**{unicode_char} {weather_description.capitalize()}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Temperature", value=f"**{tempatrue}\u00B0C**", inline=True)
            embed.add_field(name="Humidty", value=f"**{humidity}%**", inline=True)
            embed.set_thumbnail(url=f"http://openweathermap.org/img/wn/{icon_code}.png")
            embed.set_footer(text="Data provided by OpenWeatherMap")

            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Could not fetch weather data. Please check the location and try agian.", ephemeral=True)
        
    except requests.RequestException as e:
        await interaction.response.send_message("An error occured while fetching weather data. Please try agian later.", ephemeral=True)
        logging.critical(f"Weather command error: {e}")

@bot.tree.command(name="remind-me", description="Sets a reminder and will remind you after a certin amount of time")
async def remind_me(interaction: discord.Interaction, time: int, *, message: str):
    remind_time = time * 60
    remind_time_at = discord.utils.utcnow() + timedelta(seconds=remind_time)

    if interaction.user.id not in reminders:
        reminders[interaction.user.id] = []

    reminders[interaction.user.id].append({
        "remind_time_at": remind_time_at,
        "message": message
    })

    await interaction.response.send_message(f"Reminder set for {time} minutes from now", ephemeral=True)

    asyncio.create_task(remind_user(interaction.user.id, remind_time_at, message))


@bot.tree.command(name="afk", description="Go AFK for a bit")
async def afk(interaction: discord.Interaction, message: str):
    user_id = interaction.user.id
    try:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            cursor.execute("REPLACE INTO afk_status (user_id, afk_message) VALUES (%s, %s)", (user_id, message))
            connection.commit()
            cursor.close()
            connection.close()
            await interaction.response.send_message(f"<@{user_id}> Has gone afk | (MSG: **{message}**)", delete_after=5)
        else:
            await interaction.response.send_message("Failed to connect to the database", delete_after=5)
    except Error as e:
        logging.error(f"Error: {e}")

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(user="The user to ban", reason="The reason to ban the user")
async def ban(interaction: discord.Interaction, user: discord.User, reason: str = "No reason Provided"):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command can only be used in guild.", ephemeral=True)
        return
    
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("You do not have permisson to ban members.", ephemeral=True)
        return

    member = guild.get_member(user.id)
    if member is None:
        await interaction.response.send_message("User not found in this guild.", ephemeral=True)
        return
    
    if member.guild_permissions.administrator:
        await interaction.response.send_message("You can not ban a admin.", ephemeral=True)
        return
    
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("INSERT INTO bans (user_id, reason, banned_by, timestamp) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE reason=%s, banned_by=%s, timestamp=%s", (user.id, reason, interaction.user.id, datetime.now(), reason, interaction.user.id, datetime.now()))
    connection.commit()
    cursor.close()
    connection.close()

    await member.ban(reason=reason)
    await interaction.response.send_message(f"Successfully banned {user} for reason: {reason}")

app = Flask(__name__, static_folder=os.path.abspath("transcripts/"))
app.secret_key = os.urandom(24)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('gmail_user')
app.config['MAIL_PASSWORD'] = os.getenv('gmail_psw')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('gmail_sender')

mail = Mail(app)

app.config['GITHUB_CLIENT_ID'] = os.getenv('github_client_id')
app.config['GITHUB_CLIENT_SECRET'] = os.getenv('github_client_secret')
oauth = OAuth(app)
github = oauth.register(
    'github',
    client_id=app.config['GITHUB_CLIENT_ID'],
    client_secret=app.config['GITHUB_CLIENT_SECRET'],
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    refresh_token_url=None,
    redirect_uri='http://picked-next-horse.ngrok-free.app/auth/callback',
    client_kwargs={'scope': 'user:email'},
)

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    headers = request.headers

    logging.info(f"Webhook payload: {payload}")
    logging.info(f"Webhook headers: {headers}")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return "Invalid JSON", 400

    if event.get('event_type') == 'CHECKOUT.ORDER.APPROVED':
        order_id = event['resource']['id']
        user_id = int(event['resource']['purchase_units'][0]['custom_id'])

        try:
            capture_response = capture_paypal_order(order_id)
            logging.info(f"Capture Response: {capture_response}")

            if capture_response.get('status') == 'COMPLETED':
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT INTO premium_users (id) VALUES (%s) ON DUPLICATE KEY UPDATE id=id", (user_id,))
                conn.commit()
                conn.close()
                logging.info(f"User {user_id} granted premium access.")
        except Exception as e:
            logging.error(f"Error processing capture: {e}")

    return "Success", 200

@app.route('/', methods=['GET'])
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="1; url=https://picked-next-horse.ngrok-free.app/port" />
        <link rel="stylesheet" href="{{ url_for('static', filename='styles.css' )}}">
    </head>
    <body>
        <h1>Redirecting</h1>
    </body>
    </html>                  
    """)

@app.route('/transcript/<path:filename>')
async def download_transcript(filename):
    transcript_dir = '/transcripts'

    file_path = os.path.join(transcript_dir, filename)

    print(f"Requested file path: {file_path}")

    if not os.path.isfile(file_path):
        print(f"File not found at: {file_path}")
        abort(404, description="Transcript not found")

    return send_from_directory(transcript_dir, filename)



@app.route('/port', methods=['GET', 'POST'])
def port():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>My Portfolio</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
        <style>
            body {
                margin: 0;
                font-family: 'Roboto', sans-serif;
                background-color: #ffffff;
                color: #000000;
                line-height: 1.6;
                display: flex;
                flex-direction: column;
                min-height: 100vh;
                transition: background-color 0.3s, color 0.3s;
            }
            body.dark-theme {
                background: #0d1117;
                color: #c9d1d9;
            }
            header {
                text-align: center;
                padding: 60px 0;
            }
            header h1 {
                font-size: 2.5rem;
                font-weight: 700;
                margin-bottom: 10px;
                color: #58a6ff;
            }
            .container {
                max-width: 900px;
                margin: 0px auto;
                padding: 20px;
                flex-grow: 1;
            }
            section {
                margin: 40px 0;
            }
            h2 {
                font-size: 1.75rem;
                font-weight: 500;
                margin-bottom: 15px;
                color: #58a6ff;
            }
            p {
                margin-bottom: 15px;
            }
            .skills, .projects {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
            }
            .skills div, .projects div {
                background-color: #f0f0f0;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                transition: transform 0.3s ease-in-out;
            }
            body.dark-theme .skills div, .body.dark-theme .projects div {
                background-color: #161b22;
            }
            .skills div:hover, .projects div:hover {
                transform: translateY(-5px);
            }
            .flash-message {
                background-color: #28a745;
                padding: 15px;
                margin-bottom: 20px;
                border-radius: 5px;
                color: #fff;
                text-align: center;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            }
            body.dark-theme .flash-message {
            	background-color: #28a745;
            }
            footer {
                text-align: center;
                padding: 20px 0;
                font-size: 0.9rem;
                color: #8b949e;
            }
            .theme-toggle-btn {
                position: fixed;
                top: 20px;
                right: 20px;
                width: 30px;
                height: 30px;
                background-image: url('https://raw.githubusercontent.com/iHaveTailsyt/PBPD/5185963ceb57f2365b1b45a1887ab29a7b60783f/moon.svg');
                background-size: cover;
                border: none;
                border-radius: 50%;
                cursor: pointer;
                transition: background-color 0.3s ease-in-out;
            }
            body.dark-theme .theme-toggle-btn {
                background-image: url('https://raw.githubusercontent.com/iHaveTailsyt/PBPD/5185963ceb57f2365b1b45a1887ab29a7b60783f/sun.svg');
            }
            .auth {
                text-align: center;
                margin-top: 20px;
            }
            .auth a {
                text-decoration: none;
                color: #58a6ff;
                font-size: 1.1rem;
                border: 1px solid #58a6ff;
                border-radius: 5px;
                padding: 10px 20px;
                transition: background-color 0.3s, color 0.3s;
            }
            .auth a:hover {
                background-color: #58a6ff;
                color: #fff;
            }
            a {
                color: #ADD8E6;
                text-decoration: none;
            }
            a:visited {
                color: #ADD8E6;
            }
            a:hover {
                color: #87CEFA;
            }
        </style>
    </head>
    <body>
        <header>
            <h1>My Portfolio</h1>
        </header>
        <button class="theme-toggle-btn" onclick="toggleTheme()"></button>
        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="flash-message">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            <section id="about">
                <h2>About Me</h2>
                <p>Hello! I'm an aspiring developer with a passion for creating web applications. I enjoy learning new technologies and improving my skills. I am a student at CRMS</p>
            </section>
            <section id="skills">
                <h2>Skills</h2>
                <div>
                    <h3>Frontend Development</h3>
                    <p>HTML, CSS, JavaScript, React, Next.js, Typescript</p>
                </div>
                <div>
                    <h3>Backend Development</h3>
                    <p>Python, Flask, Node.js, Express, SQL</p>
                </div>
            </section>
            <section id="projects">
                <h2>Projects</h2>
                <div>
                    <h3>Website + API</h3>
                    <p>This project happens to be this site Welcome The API is rendered in <code style="font-size: 1.2em;">/webhook</code> And im working on adding more stuff to this site for now its just this and the api </p>
                </div>
                <div>
                    <h3>Skye</h3>
                    <p>Skye is a general purpose discord bot to find the code please click <a href="https://github.com/iHaveTailsyt/Skye" target="__blank">here</a></p>
                </div>
            </section>
            <section class="auth">
                {% if 'user' in session %}
                    <a href="{{ url_for('logout') }}">Logout</a>
                {% else %}
                    <a href="{{ url_for('login') }}">Login with GitHub</a>
                {% endif %}
            </section>
        </div>
        <footer>
            &copy; <span id="year"></span> Justin Konetsky. All Rights Reserved.
            To contact me please click <a href="http://picked-next-horse.ngrok-free.app/port/contact" target="_self">here.</a>
        </footer>
        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const yearSpan = document.getElementById('year');
                if (yearSpan) {
                    yearSpan.textContent = new Date().getFullYear();
                }
            });

            function setTheme(theme) {
                document.body.className = theme
                document.cookie = `theme=${theme};path=/;max-age=${60 * 60 * 24 * 365}`
            }

            function toggleTheme() {
                let currentTheme = document.body.className;
                let newTheme = currentTheme === 'dark-theme' ? '' : 'dark-theme';
                setTheme(newTheme);
            }

            function applySavedTheme() {
                const cookies = document.cookie.split(';');
                let theme = '';
                cookies.forEach(cookie => {
                    let [key, value] = cookie.split('=').map(c => c.trim());
                    if (key === 'theme') {
                        theme = value;
                    }
            });
            if (theme) {
                document.body.className = theme;
            }
        }

            applySavedTheme();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/auth/login')
def login():
    redirect_uri = url_for('auth_callback', _external=True)
    return github.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    token = github.authorize_access_token()
    logging.info(token)
    resp = github.get('https://api.github.com/user')
    logging.info(resp)
    user_info = resp.json()
    logging.info(user_info)
    callback_code = request.args.get('code')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO authed_users (callback_code) VALUES (%s)", (callback_code,))
    conn.commit()
    cursor.close()
    conn.close

    session['user'] = user_info
    flash("You were successfully logged in.")
    return redirect(url_for('port'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    if request.method == 'GET':
        return render_template('process.html')
    time.sleep(1)
    flash("You were successfully logged out.")
    return redirect(url_for('port'))

@app.route('/port/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')

        # Send email
        msg = Message('New Contact Message from Portfolio', recipients=['ihavetails@gmail.com', 'skye.innosphere@gmail.com'])
        msg.body = f"Name: {name}\nEmail: {email}\n\nMessage:\n{message}"
        mail.send(msg)

        

        flash('Thank you for reaching out! Your message has been sent.', 'success')
        return redirect(url_for('contact_success'))
        
    return render_template('index.html', methods=['GET', 'POST'])

@app.route('/contact/success/callback?code=200?redir=True?timeout=5?12241=yes',  methods=['GET'])
def contact_success():
    if request.method == 'GET':
        return render_template('process.html')
    time.sleep(1)
    return redirect(url_for('contact_callback'))

@app.route('/contact/callback')
def contact_callback():
    return redirect(url_for('port'))

@app.route('/discord/invite', methods=['GET'])
async def dis_invite():
    if request.method == 'GET':
        return render_template('process.html')
    time.sleep(1)
    return redirect(location='https://discord.gg/QPSasbcuSt')

if __name__ == "__main__":
    import threading

    bot.start_time = time.time()

    url = "http://picked-next-horse.ngrok-free.app/"

    headers = {
        "ngrok-skip-browser-warning": "true"
    }

    def send_request():
        try:
            response = requests.get(url, headers=headers)
            print({response.status_code})
        except requests.exceptions.RequestException as e:
            pass

    def run_flask():
        app.run(port=5000)


    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    bot.run(token)

    while True:
        send_request()
        time.sleep(600)

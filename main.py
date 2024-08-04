import time
from discord.ext import commands
import discord
import os
import mysql.connector
import requests
import json
import base64
from flask import Flask, abort, jsonify, request, render_template_string, send_from_directory
from dotenv import load_dotenv
import logging
from discord.ui import Button, View

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
prefix = ","
bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)
token = os.getenv('token')

owner_id = 969809822176411649

# Database configuration
db_config = {
    'user': 'inferno',
    'password': 'root',
    'host': 'localhost',
    'database': 'atlas_database'
}

# PayPal configuration
paypal_client_id = os.getenv('paypal_client_id')
paypal_secret = os.getenv('paypal_secret')
paypal_api_base = 'https://api.paypal.com'

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
    </head>
    <body>
        <div class='header'>
            <h1>Ticket Transcript</h1>
            <p>This transcript was generated on {current_time}</p>
        </div>
    """

    for message in messages:
        user_info = users_info[message['author_id']]
        html_content += f"""
        <div class='message'>
            <img src='{user_info['avatar_url']}' class='user-pfp' />
            <div class='message-content'>
                <strong class='user'>{user_info['display_name']}
                    <div class='user-info'>
                        <p><strong>Member Since:</strong> {user_info['joined_at'].strftime('%b %d, %Y')}</p>
                        <p><strong>Member ID:</strong> {user_info['id']}</p>
                        <p><strong>Message Count:</strong> {user_info['message_count']}</p>
                    </div>
                </strong>
                <p>{message['content']}</p>
                <div class='message-images'>
        """

        for attachment in message['attachments']:
            if attachment['url']:
                html_content += f"<img src='{attachment['url']}' alt='attachment' />"

        html_content += "</div></div></div>"
    
    html_content += "<div class='footer'><p>End of transcript</p></div></body></html>"
    return html_content

async def create_ticket_channel(guild, category_id, channel_name):
    category = discord.utils.get(guild.categories, id=category_id)
    if category:
        channel = await guild.create_text_channel(name=channel_name, category=category)
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

        channel = await create_ticket_channel(guild, category_id, ticket_name)

        if channel:
            await channel.send(
                embed=discord.Embed(title="New Ticket", description=f"Thank you <@{interaction.user.id}> for making a ticket our support team will be with you soon please describe the issue or having or what you need", color=discord.Color.blue()),
                view=TicketView(channel, interaction.user.id)
            )
            await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("Failed to create the ticket channel", ephemeral=True)

app = Flask(__name__, static_folder=os.path.abspath("transcripts/"))

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
    logging.info('Payment completed')
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="3; url=https://discord.gg/QPSasbcuSt" />
    </head>
    <body>
        <h1>Payment confirmed. | Redirecting</h1>
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

if __name__ == "__main__":
    import threading

    def run_flask():
        app.run(port=5000)

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    bot.run(token)

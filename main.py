from discord.ext import commands
import discord
import os
import mysql.connector
import requests
import json
import base64
from flask import Flask, jsonify, request
from dotenv import load_dotenv
import logging


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
bot = commands.Bot(command_prefix=prefix, intents=intents)
token = os.getenv('token')

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

def get_db_connection():
    return mysql.connector.connect(**db_config)

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
        logging.info(f"Guild ID: {guild.id} (name: {guild.name})")
        guild_count += 1

    logging.info(f"Logged in as {bot.user} | Servers: {guild_count}")

    try:
        synced_commands = await bot.tree.sync()
        logging.info(f"Synced {len(synced_commands)} Commands")
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
            user_role = guild.create_role(name=role_name, color=discord.Color(color_value))
            await interaction.user.add_roles(user_role)
            await interaction.response.send_message(f"Created role: {role_name} (Color: #{color}), Added role: {role_name} to you", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invaild color format. Please use a hexadecimal color code, e.g., #ff5733", ephemeral=True)
        except discord.DiscordException as e:
            await interaction.response.send_message(f"An error occurred while creating the role: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("You do not have premium therefor you cant run this command to get premium run `/but-premium` FYI its 9,99 EUR", ephemeral=True)


app = Flask(__name__)

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
    return 'Payment completed'

if __name__ == "__main__":
    import threading

    def run_flask():
        app.run(port=5000)

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    bot.run(token)

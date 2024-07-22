import asyncio
from flask import Flask, request, jsonify
import os
import re
import json
import requests
import logging
from web3 import Web3
from dotenv import load_dotenv
from asgiref.wsgi import WsgiToAsgi

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

# Parse environment variables
FILTER_FROM_NAMES = [name.strip() for name in os.getenv('FILTER_FROM_NAME').split(',')]
FILTER_FROM_ADDRESSES = [addr.strip() for addr in os.getenv('FILTER_FROM_ADDRESS').split(',')]
INFURA_URL = os.getenv('INFURA_URL')
WETH_ADDRESS = '0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2'
UNISWAP_V2_FACTORY_ADDRESS = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
AMOUNT_OF_ETH = float(os.getenv('AMOUNT_OF_ETH'))
PRICE_INCREASE_THRESHOLD = float(os.getenv('PRICE_INCREASE_THRESHOLD')) / 100  # Convert to fraction
PRICE_DECREASE_THRESHOLD = float(os.getenv('PRICE_DECREASE_THRESHOLD')) / 100  # Convert to fraction
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Additional options
SEND_TELEGRAM_MESSAGES = True  # Set to True to enable sending Telegram messages
ALLOW_MULTIPLE_TRANSACTIONS = True  # Set to True to allow multiple concurrent transactions

# Create a dictionary mapping names to addresses
NAME_TO_ADDRESS = dict(zip(FILTER_FROM_NAMES, FILTER_FROM_ADDRESSES))

# Initialize web3
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Load the Uniswap V2 Factory ABI
uniswap_v2_factory_abi = json.loads('[{"constant":true,"inputs":[{"internalType":"address","name":"tokenA","type":"address"},{"internalType":"address","name":"tokenB","type":"address"}],"name":"getPair","outputs":[{"internalType":"address","name":"","type":"address"}],"payable":false,"stateMutability":"view","type":"function"}]')

# Load the Uniswap V2 Pair ABI
with open('IUniswapV2Pair.json') as file:
    uniswap_v2_pair_abi = json.load(file)["abi"]

# Load the Uniswap V2 ERC20 ABI
with open('IUniswapV2ERC20.json') as file:
    uniswap_v2_erc20_abi = json.load(file)["abi"]

# Create factory contract instance
uniswap_v2_factory = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_FACTORY_ADDRESS), abi=uniswap_v2_factory_abi)

def send_telegram_message(message):
    """
    Sends a message to the configured Telegram chat.
    """
    if not SEND_TELEGRAM_MESSAGES:
        logging.info("Sending Telegram messages is disabled.")
        logging.info(f"Message that would be sent: {message}")
        return

    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    
    # Escape special characters for MarkdownV2
    escape_chars = r'\_~`>#+-=|{}.!'
    escaped_message = re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', message)

    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': escaped_message,
        'parse_mode': 'MarkdownV2',
        'disable_web_page_preview': True
    }

    logging.info(f"Sending Telegram message: {escaped_message}")

    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        logging.info(f"Telegram response: {response.json()}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error sending message to Telegram: {e}")
        if response is not None:
            logging.error(f"Response content: {response.content}")

def filter_message(data):
    from_name = data.get('from_name')
    action_text = data.get('action_text')
    passed_filters = []

    # Remove backslashes from action_text
    action_text_cleaned = action_text.replace('\\', '')

    # Check if from_name matches any of the names in FILTER_FROM_NAMES
    if from_name in FILTER_FROM_NAMES:
        logging.info(f"FILTER 1 — 'from_name' : '{from_name}' — PASSED")
        passed_filters.append("'from_name'")
    else:
        logging.info(f"FILTER 1 — 'from_name': '{from_name}' — FAILED")
        return False

    # Check if action_text_cleaned includes 'ETH For'
    if 'ETH For' in action_text_cleaned:
        logging.info(f"FILTER 2 — 'action_text' includes 'ETH For' — PASSED")
        passed_filters.append("'action_text'")
        return True

    logging.info(f"FILTER 2 — 'action_text' does not include 'ETH For' — FAILED")
    return False

def extract_token_address(action_text):
    # Use regex to find the token address in the action text after 'ETH For'
    eth_for_index = action_text.find('ETH For')
    if eth_for_index == -1:
        return None
    action_text_after_eth_for = action_text[eth_for_index:]
    match = re.search(r'https://etherscan.io/token/0x[0-9a-fA-F]{40}', action_text_after_eth_for)
    if match:
        token_address = match.group().split('/')[-1]
        return token_address
    return None

def get_token_details(token_address):
    token_contract = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=uniswap_v2_erc20_abi)
    name = token_contract.functions.name().call()
    symbol = token_contract.functions.symbol().call()
    decimals = token_contract.functions.decimals().call()
    return name, symbol, decimals

def get_token_price(token_address, token_decimals):
    # Fetch pair address from Uniswap V2 Factory contract
    pair_address = uniswap_v2_factory.functions.getPair(Web3.to_checksum_address(token_address), Web3.to_checksum_address(WETH_ADDRESS)).call()
    
    if pair_address == '0x0000000000000000000000000000000000000000':
        logging.info("No pair found for this token.")
        return None, None

    # Create pair contract instance
    pair_contract = web3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=uniswap_v2_pair_abi)
    
    # Fetch reserves from the pair contract
    reserves = pair_contract.functions.getReserves().call()
    reserve_weth, reserve_token = reserves[0], reserves[1]

    # Determine which reserve is for WETH and which is for the token
    if Web3.to_checksum_address(token_address) < Web3.to_checksum_address(WETH_ADDRESS):
        reserve_token, reserve_weth = reserves[0], reserves[1]
    else:
        reserve_weth, reserve_token = reserves[0], reserves[1]

    # Adjust reserves
    adjusted_reserve_token = reserve_token / (10 ** token_decimals)
    adjusted_reserve_weth = reserve_weth / (10 ** 18)

    # Calculate price
    token_price = adjusted_reserve_weth / adjusted_reserve_token
    return token_price, pair_address

def calculate_token_amount(eth_amount, token_price):
    return eth_amount / token_price

async def monitor_price(token_address, initial_price, token_decimals, transaction_details):
    from_name = transaction_details['from_name']
    tx_hash = transaction_details['tx_hash']
    symbol = transaction_details['symbol']
    token_amount = transaction_details['token_amount']
    from_address = NAME_TO_ADDRESS[from_name]
    
    monitoring_id = tx_hash[:8]  # Create a short identifier for the transaction

    while True:
        current_price, _ = get_token_price(token_address, token_decimals)
        if current_price is None:
            logging.info("Failed to fetch the current price.")
            await asyncio.sleep(5)
            continue

        price_increase = (current_price - initial_price) / initial_price
        price_decrease = (initial_price - current_price) / initial_price
        percent_change = ((current_price - initial_price) / initial_price) * 100

        if price_increase >= PRICE_INCREASE_THRESHOLD:
            logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — Token price increased by {price_increase * 100:.2f}%. Selling the token.")
            break
        elif price_decrease >= PRICE_DECREASE_THRESHOLD:
            logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — Token price decreased by {price_decrease * 100:.2f}%. Selling the token.")
            break

        logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — {token_amount} {symbol}.")
        await asyncio.sleep(5)

    # Calculate and print the amount of ETH received from the sale
    eth_received = token_amount * current_price
    profit_or_loss = eth_received - AMOUNT_OF_ETH
    logging.info(f"Monitoring {monitoring_id} — Would have sold {token_amount} for approximately {eth_received} ETH.")
    
    tx_hash_link = f"[{tx_hash}](https://etherscan.io/tx/{tx_hash})"
    from_name_link = f"[{from_name}](https://etherscan.io/address/{from_address})"
    
    messageS = (
        f'🟢 *SELL!* 🟢\n\n'
        f'*From:*\n{from_name_link}\n\n'
        f'*Original Transaction Hash:*\n{tx_hash_link}\n\n'
        f'*Action:*\nSold {token_amount} [{symbol}](https://etherscan.io/token/{token_address}) for approximately {eth_received} ETH.\n\n'
        f'*Profit/Loss:*\n{profit_or_loss} ETH.'
    )
    send_telegram_message(messageS)

@app.route('/transaction', methods=['POST'])
async def transaction():
    data = request.json
    logging.info('—————————————————————————————————————————————————————————————————————————————————————————————————————————')
    logging.info(f"Received transaction data: {data}")
    if filter_message(data):
        logging.info("Yes, it passes the filters")
        action_text_cleaned = data.get('action_text').replace('\\', '')
        token_address = extract_token_address(action_text_cleaned)
        if token_address:
            logging.info(f"Extracted token address: {token_address}")
            name, symbol, decimals = get_token_details(token_address)
            logging.info(f"Token name: {name}")
            logging.info(f"Token symbol: {symbol}")
            initial_price, pair_address = get_token_price(token_address, decimals)
            if initial_price is not None:
                logging.info(f"Pair address: {pair_address}")
                logging.info(f"Token price: {initial_price} ETH")
                token_amount = calculate_token_amount(AMOUNT_OF_ETH, initial_price)
                logging.info(f"Approximately {token_amount} {symbol} would be purchased for {AMOUNT_OF_ETH} ETH.")

                # Send Telegram message for buy
                from_name = data.get('from_name')
                tx_hash = data.get('tx_hash')
                from_address = NAME_TO_ADDRESS[from_name]
                tx_hash_link = f"[{tx_hash}](https://etherscan.io/tx/{tx_hash})"
                from_name_link = f"[{from_name}](https://etherscan.io/address/{from_address})"
                messageB = (
                    f'🟡 *BUY!* 🟡\n\n'
                    f'*From:*\n{from_name_link}\n\n'
                    f'*Original Transaction Hash:*\n{tx_hash_link}\n\n'
                    f'*Action:*\nApproximately {token_amount} [{symbol}](https://etherscan.io/token/{token_address}) purchased for {AMOUNT_OF_ETH} ETH.\n\n'
                )
                send_telegram_message(messageB)

                # Prepare transaction details for monitoring
                transaction_details = {
                    'from_name': from_name,
                    'tx_hash': tx_hash,
                    'symbol': symbol,
                    'token_amount': token_amount,
                }

                if ALLOW_MULTIPLE_TRANSACTIONS:
                    asyncio.create_task(monitor_price(token_address, initial_price, decimals, transaction_details))
                else:
                    await monitor_price(token_address, initial_price, decimals, transaction_details)
            else:
                logging.info("Token price not available.")
        else:
            logging.info("Token address not found in the action text.")
    else:
        logging.info("No, it does not pass the filters")
    return jsonify({'status': 'success'}), 200

def run_server():
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    asgi_app = WsgiToAsgi(app)
    import uvicorn
    uvicorn.run(asgi_app, host='0.0.0.0', port=5000, timeout_keep_alive=0)

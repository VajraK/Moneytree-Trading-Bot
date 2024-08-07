import asyncio
from flask import Flask, request, jsonify
import os
import json
import logging
from web3 import Web3
from dotenv import load_dotenv
from asgiref.wsgi import WsgiToAsgi
from datetime import datetime, timezone
from pieces.filters import filter_message, extract_token_address, get_token_details
from pieces.uniswap import get_uniswap_v2_price, get_uniswap_v3_price
from pieces.text_utils import insert_zero_width_space
from pieces.telegram_utils import send_telegram_message
from pieces.market_cap import calculate_market_cap
from pieces.price_change_checker import check_no_change_threshold
from pieces.trading import buy_token, sell_token, log_transaction_details  # Import the trading functions

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
file_handler = logging.FileHandler('logs/mtdb_logs.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Load environment variables
load_dotenv()

# Parse environment variables
FILTER_FROM_NAMES = [name.strip() for name in os.getenv('FILTER_FROM_NAME').split(',')]
FILTER_FROM_ADDRESSES = [addr.strip() for addr in os.getenv('FILTER_FROM_ADDRESS').split(',')]
INFURA_URL = os.getenv('INFURA_URL')
WETH_ADDRESS = '0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2'
UNISWAP_V2_FACTORY_ADDRESS = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
UNISWAP_V3_FACTORY_ADDRESS = '0x1F98431c8aD98523631AE4a59f267346ea31F984'  # Uniswap V3 Factory Address
AMOUNT_OF_ETH = float(os.getenv('AMOUNT_OF_ETH'))
PRICE_INCREASE_THRESHOLD = float(os.getenv('PRICE_INCREASE_THRESHOLD')) / 100  # Convert to fraction
PRICE_DECREASE_THRESHOLD = float(os.getenv('PRICE_DECREASE_THRESHOLD')) / 100  # Convert to fraction
NO_CHANGE_THRESHOLD_PERCENT = float(os.getenv('NO_CHANGE_THRESHOLD_PERCENT')) / 100  # Convert to fraction
NO_CHANGE_TIME_MINUTES = int(os.getenv('NO_CHANGE_TIME_MINUTES'))  # Time in minutes
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MOONBAG = float(os.getenv('MOONBAG', 0)) / 100  # Convert to fraction
MIN_MARKET_CAP = float(os.getenv('MIN_MARKET_CAP'))  # Minimum market cap in USD
MAX_MARKET_CAP = float(os.getenv('MAX_MARKET_CAP'))  # Maximum market cap in USD

# Additional options
SEND_TELEGRAM_MESSAGES = True  # Set to True to enable sending Telegram messages
ALLOW_MULTIPLE_TRANSACTIONS = True  # Set to True to allow multiple concurrent transactions
ENABLE_MARKET_CAP_FILTER = True  # Set to True to enable the Market Cap Filter
ENABLE_PRICE_CHANGE_CHECKER = True  # Set to True to enable the Price Change Checker
ENABLE_TRADING = False  # Set to True to enable trading

# Create a dictionary mapping names to addresses
NAME_TO_ADDRESS = dict(zip(FILTER_FROM_NAMES, FILTER_FROM_ADDRESSES))

# Initialize web3
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Load the Uniswap V2 Factory ABI
with open('abis/IUniswapV2Factory.json') as file:
    uniswap_v2_factory_abi = json.load(file)["abi"]

# Load the Uniswap V2 Pair ABI
with open('abis/IUniswapV2Pair.json') as file:
    uniswap_v2_pair_abi = json.load(file)["abi"]

# Load the Uniswap V2 ERC20 ABI
with open('abis/IUniswapV2ERC20.json') as file:
    uniswap_v2_erc20_abi = json.load(file)["abi"]

# Load the Uniswap V3 Factory ABI
with open('abis/IUniswapV3Factory.json') as file:
    uniswap_v3_factory_abi = json.load(file)

# Load the Uniswap V3 Pool ABI
with open('abis/IUniswapV3Pool.json') as file:
    uniswap_v3_pool_abi = json.load(file)

# Create factory contract instances
uniswap_v2_factory = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_FACTORY_ADDRESS), abi=uniswap_v2_factory_abi)
uniswap_v3_factory = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_FACTORY_ADDRESS), abi=uniswap_v3_factory_abi)

def calculate_token_amount(eth_amount, token_price):
    return eth_amount / token_price

def format_large_number(number):
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    elif number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    elif number >= 1_000:
        return f"{number / 1_000:.1f}K"
    else:
        return str(number)

async def monitor_price(token_address, initial_price, token_decimals, transaction_details):
    from_name = transaction_details['from_name']
    tx_hash = transaction_details['tx_hash']
    symbol = transaction_details['symbol']
    token_amount = transaction_details['token_amount']
    from_address = NAME_TO_ADDRESS[from_name]
    
    monitoring_id = tx_hash[:8]  # Create a short identifier for the transaction

    start_time = datetime.now(timezone.utc)
    sell_reason = ''
    price_history = []

    while True:
        current_price, _ = get_uniswap_v2_price(web3, uniswap_v2_factory, token_address, WETH_ADDRESS, token_decimals, uniswap_v2_pair_abi)
        if current_price is None:
            current_price, _ = get_uniswap_v3_price(web3, uniswap_v3_factory, token_address, WETH_ADDRESS, token_decimals, uniswap_v3_pool_abi)
            if current_price is None:
                logging.info("Failed to fetch the current price.")
                await asyncio.sleep(5)
                continue

        price_history.append((datetime.now(timezone.utc), current_price))

        price_increase = (current_price - initial_price) / initial_price
        price_decrease = (initial_price - current_price) / initial_price
        percent_change = ((current_price - initial_price) / initial_price) * 100

        if price_increase >= PRICE_INCREASE_THRESHOLD:
            logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — Token price increased by {price_increase * 100:.2f}%. Selling the token.")
            token_amount_to_sell = token_amount * (1 - MOONBAG)
            sell_reason = f'Price increased by {price_increase * 100:.2f}%'
            break
        elif price_decrease >= PRICE_DECREASE_THRESHOLD:
            logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — Token price decreased by {price_decrease * 100:.2f}%. Selling the token.")
            token_amount_to_sell = token_amount
            sell_reason = f'Price decreased by {price_decrease * 100:.2f}%'
            break

        if ENABLE_PRICE_CHANGE_CHECKER:
            no_change, token_amount_to_sell, sell_reason, start_time = check_no_change_threshold(start_time, price_history, monitoring_id, symbol, token_amount)
            if no_change:
                break

        logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — {token_amount} {symbol}.")
        await asyncio.sleep(3)

    if token_amount_to_sell is not None:
        # Calculate and print the amount of ETH received from the sale
        eth_received = token_amount_to_sell * current_price
        profit_or_loss = eth_received - (AMOUNT_OF_ETH * (token_amount_to_sell / token_amount))
        
        profit_or_loss_display = f"🏆 {profit_or_loss} ETH" if profit_or_loss > 0 else f"{profit_or_loss} ETH"

        # LOG the profit or loss and the from_name
        logging.info(f"LOG—Profit/Loss: {profit_or_loss_display}")
        logging.info(f"LOG—From: {from_name}")

        # If trading is enabled, execute the sell transaction
        if ENABLE_TRADING:
            sell_tx_hash = sell_token(token_address, token_amount_to_sell)
            logging.info(f"Monitoring {monitoring_id} — Sell transaction sent with hash: {sell_tx_hash}")
            log_transaction_details(sell_tx_hash)
            messageS = (
                f'🟢 *SELL!* 🟢\n\n'
                f'*From:*\n[{from_name}](https://etherscan.io/address/{from_address})\n\n'
                f'*Original Transaction Hash:*\n[{tx_hash}](https://etherscan.io/tx/{tx_hash})\n\n'
                f'*Sell Transaction Hash:*\n[{sell_tx_hash}](https://etherscan.io/tx/{sell_tx_hash})\n\n'
                f'*Action:*\nSold {token_amount_to_sell} [{symbol}](https://etherscan.io/token/{token_address}) for approximately {eth_received} ETH.\n\n'
                f'*Reason:*\n{sell_reason}\n\n'
                f'*Profit/Loss:*\n{profit_or_loss_display}.\n\n'
            )
        else:
            logging.info(f"Monitoring {monitoring_id} — Sold {token_amount_to_sell} for approximately {eth_received} ETH.")
            messageS = (
                f'🟢 *SELL!* 🟢\n\n'
                f'*From:*\n[{from_name}](https://etherscan.io/address/{from_address})\n\n'
                f'*Original Transaction Hash:*\n[{tx_hash}](https://etherscan.io/tx/{tx_hash})\n\n'
                f'*Action:*\nSold {token_amount_to_sell} [{symbol}](https://etherscan.io/token/{token_address}) for approximately {eth_received} ETH.\n\n'
                f'*Reason:*\n{sell_reason}\n\n'
                f'*Profit/Loss:*\n{profit_or_loss_display}.\n\n'
            )
        if token_amount_to_sell != token_amount:
            messageS += f'*Moonbag:*\n{token_amount * MOONBAG} {symbol}'
        send_telegram_message(insert_zero_width_space(messageS))
    else:
        logging.info(f"Monitoring {monitoring_id} — Continuing to monitor price changes after initial period.")

@app.route('/transaction', methods=['POST'])
async def transaction():
    data = request.json
    logging.info('—————————————————————————————————————————————————————————————————————————————————————————————————————————')
    logging.info(f"Received transaction data: {data}")
    if filter_message(data, FILTER_FROM_NAMES):
        logging.info("Yes, it passes the filters")
        action_text_cleaned = data.get('action_text').replace('\\', '')
        token_address = extract_token_address(action_text_cleaned)
        if token_address:
            logging.info(f"Extracted token address: {token_address}")

            if ENABLE_MARKET_CAP_FILTER:
                # Check market cap
                market_cap_usd = calculate_market_cap(token_address)
                if market_cap_usd is None:
                    logging.info("Market cap not available. Skipping the buy.")
                    return jsonify({'status': 'failed', 'reason': 'Market cap not available'}), 400
                
                if market_cap_usd < MIN_MARKET_CAP or market_cap_usd > MAX_MARKET_CAP:
                    logging.info(f"Market cap {market_cap_usd} USD not within the specified range. Skipping the buy.")
                    return jsonify({'status': 'failed', 'reason': f'Market cap {market_cap_usd} USD not within the specified range'}), 200

            name, symbol, decimals = get_token_details(web3, token_address, uniswap_v2_erc20_abi)
            logging.info(f"Token name: {name}")
            logging.info(f"Token symbol: {symbol}")
            initial_price, pair_address = get_uniswap_v2_price(web3, uniswap_v2_factory, token_address, WETH_ADDRESS, decimals, uniswap_v2_pair_abi)
            if initial_price is None:
                initial_price, pair_address = get_uniswap_v3_price(web3, uniswap_v3_factory, token_address, WETH_ADDRESS, decimals, uniswap_v3_pool_abi)
            
            if initial_price is not None:
                logging.info(f"Pair/Pool address: {pair_address}")
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
                    f'*Copied Transaction Hash:*\n{tx_hash_link}\n\n'
                )
                if ENABLE_MARKET_CAP_FILTER:
                    messageB += f'*Market Cap:*\n{format_large_number(market_cap_usd)} USD\n\n'

                # If trading is enabled, execute the buy transaction
                if ENABLE_TRADING:
                    buy_tx_hash = buy_token(token_address, AMOUNT_OF_ETH)
                    logging.info(f"Buy transaction sent with hash: {buy_tx_hash}")
                    log_transaction_details(buy_tx_hash)
                    messageB += f'*Transaction Hash:*\n[{buy_tx_hash}](https://etherscan.io/tx/{buy_tx_hash})\n\n'
                    # Update the token amount with the actual amount bought
                    token_amount = calculate_token_amount(AMOUNT_OF_ETH, initial_price)

                messageB += (
                    f'*Action:*\nApproximately {token_amount} [{symbol}](https://etherscan.io/token/{token_address}) purchased for {AMOUNT_OF_ETH} ETH.\n'
                )

                send_telegram_message(insert_zero_width_space(messageB))

                # Prepare transaction details for monitoring
                transaction_details = {
                    'from_name': from_name,
                    'tx_hash': tx_hash,
                    'symbol': symbol,
                    'token_amount': token_amount,
                    'token_address': token_address,
                    'initial_price': initial_price,
                    'token_decimals': decimals
                }

                if ALLOW_MULTIPLE_TRANSACTIONS:
                    asyncio.create_task(monitor_price(token_address, initial_price, decimals, transaction_details))
                else:
                    await monitor_price(token_address, initial_price, decimals, transaction_details)
            else:
                logging.info("Token price not available on either Uniswap V2 or V3.")
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


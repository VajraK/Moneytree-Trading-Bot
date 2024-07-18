import time
from flask import Flask, request, jsonify
import os
import re
import json
from web3 import Web3
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# Parse environment variables
FILTER_FROM_NAMES = [name.strip() for name in os.getenv('FILTER_FROM_NAME').split(',')]
INFURA_URL = os.getenv('INFURA_URL')
WETH_ADDRESS = '0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2'
UNISWAP_V2_FACTORY_ADDRESS = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
AMOUNT_OF_ETH = float(os.getenv('AMOUNT_OF_ETH'))
PRICE_INCREASE_THRESHOLD = float(os.getenv('PRICE_INCREASE_THRESHOLD')) / 100  # Convert to fraction
PRICE_DECREASE_THRESHOLD = float(os.getenv('PRICE_DECREASE_THRESHOLD')) / 100  # Convert to fraction

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

def filter_message(data):
    from_name = data.get('from_name')
    action_text = data.get('action_text')
    passed_filters = []

    # Remove backslashes from action_text
    action_text_cleaned = action_text.replace('\\', '')

    # Check if from_name matches any of the names in FILTER_FROM_NAMES
    if from_name in FILTER_FROM_NAMES:
        print(f"FILTER 1 — 'from_name' : '{from_name}' — PASSED")
        print()
        passed_filters.append("'from_name'")
    else:
        print(f"FILTER 1 — 'from_name': '{from_name}' — FAILED")
        print()
        return False

    # Check if action_text_cleaned includes 'ETH For'
    if 'ETH For' in action_text_cleaned:
        print(f"FILTER 2 — 'action_text' includes 'ETH For' — PASSED")
        print()
        passed_filters.append("'action_text'")
        return True

    print(f"FILTER 2 — 'action_text' does not include 'ETH For' — FAILED")
    print()
    return False

def extract_token_address(action_text):
    # Use regex to find the token address in the action text
    match = re.search(r'https://etherscan.io/token/0x[0-9a-fA-F]{40}', action_text)
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
        print("No pair found for this token.")
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

def monitor_price(token_address, initial_price, token_decimals):
    while True:
        current_price, _ = get_token_price(token_address, token_decimals)
        if current_price is None:
            print("Failed to fetch the current price.")
            continue

        price_increase = (current_price - initial_price) / initial_price
        price_decrease = (initial_price - current_price) / initial_price

        if price_increase >= PRICE_INCREASE_THRESHOLD:
            print(f"Token price increased by {price_increase * 100}%. Selling the token.")
            break
        elif price_decrease >= PRICE_DECREASE_THRESHOLD:
            print(f"Token price decreased by {price_decrease * 100}%. Selling the token.")
            break

        print(f"Current price: {current_price} ETH. Monitoring...")
        time.sleep(5)

    # Calculate and print the amount of ETH received from the sale
    token_amount = calculate_token_amount(AMOUNT_OF_ETH, initial_price)
    eth_received = token_amount * current_price
    print(f"Would have sold {token_amount} for approximately {eth_received} ETH.")

@app.route('/transaction', methods=['POST'])
def transaction():
    data = request.json
    print('—————————————————————————————————————————————————————————————————————————————————————————————————————————')
    print()
    print(f"Received transaction data: {data}")
    print()
    if filter_message(data):
        print("Yes, it passes the filters")
        print()
        action_text_cleaned = data.get('action_text').replace('\\', '')
        token_address = extract_token_address(action_text_cleaned)
        if token_address:
            print(f"Extracted token address: {token_address}")
            print()
            name, symbol, decimals = get_token_details(token_address)
            print(f"Token name: {name}")
            print(f"Token symbol: {symbol}")
            print()
            initial_price, pair_address = get_token_price(token_address, decimals)
            if initial_price is not None:
                print(f"Pair address: {pair_address}")
                print()
                print(f"Token price: {initial_price} ETH")
                print()
                token_amount = calculate_token_amount(AMOUNT_OF_ETH, initial_price)
                print(f"Approximately {token_amount} {symbol} would be purchased for {AMOUNT_OF_ETH} ETH.")
                print()
                monitor_price(token_address, initial_price, decimals)
            else:
                print("Token price not available.")
        else:
            print("Token address not found in the action text.")
        print()
    else:
        print("No, it does not pass the filters")
        print()
    return jsonify({'status': 'success'}), 200

def run_server():
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    run_server()

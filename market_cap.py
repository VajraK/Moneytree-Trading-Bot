import json
from web3 import Web3
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Initialize web3
INFURA_URL = os.getenv('INFURA_URL')
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Define addresses
TOKEN_ADDRESS = '0x69420ea9361a7bbb61187a5d05b7d44a0b0002be'  # Replace with your token address
WETH_ADDRESS = '0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2'
UNISWAP_V2_FACTORY_ADDRESS = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
CHAINLINK_ETH_USD_FEED = '0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419'  # Chainlink ETH/USD Price Feed

# Load ABIs
uniswap_v2_factory_abi = json.loads('[{"constant":true,"inputs":[{"internalType":"address","name":"tokenA","type":"address"},{"internalType":"address","name":"tokenB","type":"address"}],"name":"getPair","outputs":[{"internalType":"address","name":"","type":"address"}],"payable":false,"stateMutability":"view","type":"function"}]')
with open('IUniswapV2Pair.json') as file:
    uniswap_v2_pair_abi = json.load(file)["abi"]
with open('IUniswapV2ERC20.json') as file:
    uniswap_v2_erc20_abi = json.load(file)["abi"]
chainlink_price_feed_abi = json.loads('[{"inputs":[],"name":"latestRoundData","outputs":[{"internalType":"uint80","name":"roundId","type":"uint80"},{"internalType":"int256","name":"answer","type":"int256"},{"internalType":"uint256","name":"startedAt","type":"uint256"},{"internalType":"uint256","name":"updatedAt","type":"uint256"},{"internalType":"uint80","name":"answeredInRound","type":"uint80"}],"stateMutability":"view","type":"function"}]')

# Create contract instances
uniswap_v2_factory = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_FACTORY_ADDRESS), abi=uniswap_v2_factory_abi)
chainlink_price_feed = web3.eth.contract(address=Web3.to_checksum_address(CHAINLINK_ETH_USD_FEED), abi=chainlink_price_feed_abi)

def get_eth_price_in_usd():
    latest_round_data = chainlink_price_feed.functions.latestRoundData().call()
    eth_price_in_usd = latest_round_data[1] / 1e8  # Chainlink prices have 8 decimals
    return eth_price_in_usd

def get_token_details(token_address):
    token_contract = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=uniswap_v2_erc20_abi)
    name = token_contract.functions.name().call()
    symbol = token_contract.functions.symbol().call()
    decimals = token_contract.functions.decimals().call()
    total_supply = token_contract.functions.totalSupply().call() / (10 ** decimals)
    return name, symbol, decimals, total_supply

def get_uniswap_v2_price(token_address, token_decimals):
    pair_address = uniswap_v2_factory.functions.getPair(Web3.to_checksum_address(token_address), Web3.to_checksum_address(WETH_ADDRESS)).call()
    
    if pair_address == '0x0000000000000000000000000000000000000000':
        return None, None

    pair_contract = web3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=uniswap_v2_pair_abi)
    reserves = pair_contract.functions.getReserves().call()

    reserve_weth, reserve_token = reserves[0], reserves[1]

    if Web3.to_checksum_address(token_address) < Web3.to_checksum_address(WETH_ADDRESS):
        reserve_token, reserve_weth = reserves[0], reserves[1]
    else:
        reserve_weth, reserve_token = reserves[0], reserves[1]

    adjusted_reserve_token = reserve_token / (10 ** token_decimals)
    adjusted_reserve_weth = reserve_weth / (10 ** 18)

    token_price = adjusted_reserve_weth / adjusted_reserve_token
    return token_price, pair_address

def calculate_market_cap(token_address):
    eth_price_in_usd = get_eth_price_in_usd()
    if eth_price_in_usd is None:
        print("Cannot calculate market cap without ETH price.")
        return

    name, symbol, decimals, total_supply = get_token_details(token_address)
    token_price, pair_address = get_uniswap_v2_price(token_address, decimals)
    
    if token_price is not None:
        market_cap_eth = total_supply * token_price
        market_cap_usd = market_cap_eth * eth_price_in_usd
        print(f"Token: {name} ({symbol})")
        print(f"Total Supply: {total_supply}")
        print(f"Token Price: {token_price} ETH")
        print(f"Market Cap: {market_cap_eth} ETH")
        print(f"Market Cap: {market_cap_usd} USD")
    else:
        print("Token price not available on Uniswap V2.")

# Replace 'your_token_address_here' with the actual token address
calculate_market_cap(TOKEN_ADDRESS)
import os
import json
import logging
from web3 import Web3
from dotenv import load_dotenv
from eth_account import Account
from datetime import datetime, timedelta, timezone

# Load environment variables
load_dotenv()

# Initialize web3
INFURA_URL = os.getenv('INFURA_URL')
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Wallet details
WALLET_PRIVATE_KEY = os.getenv('WALLET_PRIVATE_KEY')
WALLET_ADDRESS = web3.eth.account.from_key(WALLET_PRIVATE_KEY).address

# Uniswap Router address
UNISWAP_V2_ROUTER_ADDRESS = '0x7a250d5630b4cf539739df2c5dacf5b4c659f248'  # Uniswap V2 Router
UNISWAP_V3_ROUTER_ADDRESS = '0xE592427A0AEce92De3Edee1F18E0157C05861564'  # Uniswap V3 Router

# Load ABIs
with open('abis/IUniswapV2Router02.json') as file:
    uniswap_v2_router_abi = json.load(file)["abi"]
with open('abis/IUniswapV3Router.json') as file:
    uniswap_v3_router_abi = json.load(file)

# Create contract instances
uniswap_v2_router = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V2_ROUTER_ADDRESS), abi=uniswap_v2_router_abi)
uniswap_v3_router = web3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_ROUTER_ADDRESS), abi=uniswap_v3_router_abi)

# Constants
WETH_ADDRESS = '0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2'

def buy_token(token_address, amount_eth):
    # Determine transaction parameters
    deadline = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
    amount_out_min = 0  # You can set a more realistic amount or use a slippage tolerance mechanism

    # Create transaction
    txn = uniswap_v2_router.functions.swapExactETHForTokens(
        amount_out_min,
        [WETH_ADDRESS, Web3.to_checksum_address(token_address)],
        Web3.to_checksum_address(WALLET_ADDRESS),
        deadline
    ).buildTransaction({
        'from': WALLET_ADDRESS,
        'value': web3.toWei(amount_eth, 'ether'),
        'gas': 2000000,  # Gas limit
        'gasPrice': web3.toWei('50', 'gwei'),  # Gas price
        'nonce': web3.eth.getTransactionCount(WALLET_ADDRESS),
    })

    # Sign and send the transaction
    signed_txn = web3.eth.account.sign_transaction(txn, private_key=WALLET_PRIVATE_KEY)
    tx_hash = web3.eth.sendRawTransaction(signed_txn.rawTransaction)
    
    logging.info(f"Transaction sent with hash: {tx_hash.hex()}")
    log_transaction_details(tx_hash.hex())
    return tx_hash.hex()

def sell_token(token_address, token_amount):
    # Approve the Uniswap router to spend the tokens
    token_contract = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=uniswap_v2_router_abi)
    approve_txn = token_contract.functions.approve(
        UNISWAP_V2_ROUTER_ADDRESS,
        web3.toWei(token_amount, 'ether')
    ).buildTransaction({
        'from': WALLET_ADDRESS,
        'gas': 100000,  # Gas limit
        'gasPrice': web3.toWei('50', 'gwei'),  # Gas price
        'nonce': web3.eth.getTransactionCount(WALLET_ADDRESS),
    })

    signed_approve_txn = web3.eth.account.sign_transaction(approve_txn, private_key=WALLET_PRIVATE_KEY)
    approve_tx_hash = web3.eth.sendRawTransaction(signed_approve_txn.rawTransaction)
    logging.info(f"Approve transaction sent with hash: {approve_tx_hash.hex()}")

    # Wait for the approval to be mined
    web3.eth.waitForTransactionReceipt(approve_tx_hash)

    # Determine transaction parameters
    deadline = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
    amount_in = web3.toWei(token_amount, 'ether')
    amount_out_min = 0  # You can set a more realistic amount or use a slippage tolerance mechanism

    # Create transaction
    txn = uniswap_v2_router.functions.swapExactTokensForETH(
        amount_in,
        amount_out_min,
        [Web3.to_checksum_address(token_address), WETH_ADDRESS],
        Web3.to_checksum_address(WALLET_ADDRESS),
        deadline
    ).buildTransaction({
        'from': WALLET_ADDRESS,
        'gas': 2000000,  # Gas limit
        'gasPrice': web3.toWei('50', 'gwei'),  # Gas price
        'nonce': web3.eth.getTransactionCount(WALLET_ADDRESS),
    })

    # Sign and send the transaction
    signed_txn = web3.eth.account.sign_transaction(txn, private_key=WALLET_PRIVATE_KEY)
    tx_hash = web3.eth.sendRawTransaction(signed_txn.rawTransaction)
    
    logging.info(f"Transaction sent with hash: {tx_hash.hex()}")
    log_transaction_details(tx_hash.hex())
    return tx_hash.hex()

def log_transaction_details(tx_hash):
    tx_receipt = web3.eth.getTransactionReceipt(tx_hash)
    tx = web3.eth.getTransaction(tx_hash)

    logging.info(f"Transaction Details for {tx_hash}:")
    logging.info(f"  Block Number: {tx_receipt['blockNumber']}")
    logging.info(f"  Gas Used: {tx_receipt['gasUsed']}")
    logging.info(f"  Status: {tx_receipt['status']}")
    logging.info(f"  From: {tx['from']}")
    logging.info(f"  To: {tx['to']}")
    logging.info(f"  Value: {web3.fromWei(tx['value'], 'ether')} ETH")
    logging.info(f"  Gas Price: {web3.fromWei(tx['gasPrice'], 'gwei')} Gwei")
    logging.info(f"  Nonce: {tx['nonce']}")
    logging.info(f"  Input Data: {tx['input']}")

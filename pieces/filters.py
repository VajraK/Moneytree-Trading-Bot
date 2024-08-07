import re
import logging
from web3 import Web3

# Define the file path where cleaned action texts will be saved
ACTION_TEXT_FILE = 'logs/cleaned_action_texts.log'

def filter_message(data, filter_from_names):
    from_name = data.get('from_name')
    action_text = data.get('action_text')
    passed_filters = []

    # Remove backslashes from action_text
    action_text_cleaned = action_text.replace('\\', '')

    # Save the cleaned action text to a file
    save_action_text(action_text_cleaned)

    # Check if from_name matches any of the names in filter_from_names
    if from_name in filter_from_names:
        logging.info(f"FILTER 1 — 'from_name' : '{from_name}' — PASSED")
        passed_filters.append("'from_name'")
    else:
        logging.info(f"FILTER 1 — 'from_name': '{from_name}' — FAILED")
        return False

    # Check if action_text_cleaned includes 'ETH For' (Uniswap) or 'ETH (xyz) for' (Banana Gun)
    if 'ETH For' in action_text_cleaned or re.search(r'ETH \〈[^\)]+\〉 for', action_text_cleaned):
        logging.info(f"FILTER 2 — 'action_text' includes 'ETH For' or 'ETH (xyz) for' — PASSED")
        passed_filters.append("'action_text'")
        return True

    logging.info(f"FILTER 2 — 'action_text' does not include 'ETH For' or 'ETH (xyz) for' — FAILED")
    return False

def extract_token_address(action_text):
    # Use regex to find the token address in the action text after 'ETH For' or 'ETH 〈xyz〉 for'
    eth_for_index = action_text.find('ETH For')
    if eth_for_index == -1:
        eth_for_index = action_text.find('ETH 〈')
        if eth_for_index == -1:
            return None
        eth_for_index = action_text.find(' for', eth_for_index)
        if eth_for_index == -1:
            return None
    action_text_after_eth_for = action_text[eth_for_index:]
    match = re.search(r'https://etherscan.io/token/0x[0-9a-fA-F]{40}', action_text_after_eth_for)
    if match:
        token_address = match.group().split('/')[-1]
        return token_address
    return None

def get_token_details(web3, token_address, uniswap_v2_erc20_abi):
    token_contract = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=uniswap_v2_erc20_abi)
    name = token_contract.functions.name().call()
    symbol = token_contract.functions.symbol().call()
    decimals = token_contract.functions.decimals().call()
    return name, symbol, decimals

def save_action_text(action_text_cleaned):
    """Save the cleaned action text to a file."""
    with open(ACTION_TEXT_FILE, 'a') as file:
        file.write(action_text_cleaned + '\n')
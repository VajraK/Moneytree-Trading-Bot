import logging
from web3 import Web3

def get_uniswap_v2_price(web3, uniswap_v2_factory, token_address, weth_address, token_decimals, uniswap_v2_pair_abi):
    # Fetch pair address from Uniswap V2 Factory contract
    pair_address = uniswap_v2_factory.functions.getPair(Web3.to_checksum_address(token_address), Web3.to_checksum_address(weth_address)).call()
    
    if pair_address == '0x0000000000000000000000000000000000000000':
        return None, None

    # Create pair contract instance
    pair_contract = web3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=uniswap_v2_pair_abi)
    
    # Fetch reserves from the pair contract
    reserves = pair_contract.functions.getReserves().call()
    reserve_weth, reserve_token = reserves[0], reserves[1]

    # Determine which reserve is for WETH and which is for the token
    if Web3.to_checksum_address(token_address) < Web3.to_checksum_address(weth_address):
        reserve_token, reserve_weth = reserves[0], reserves[1]
    else:
        reserve_weth, reserve_token = reserves[0], reserves[1]

    # Adjust reserves
    adjusted_reserve_token = reserve_token / (10 ** token_decimals)
    adjusted_reserve_weth = reserve_weth / (10 ** 18)

    # Calculate price
    token_price = adjusted_reserve_weth / adjusted_reserve_token
    return token_price, pair_address

def get_uniswap_v3_price(web3, uniswap_v3_factory, token_address, weth_address, token_decimals, uniswap_v3_pool_abi):
    fee_tiers = [500, 3000, 10000]
    
    for fee in fee_tiers:
        try:
            # Fetch pool address from Uniswap V3 Factory contract
            pool_address = uniswap_v3_factory.functions.getPool(Web3.to_checksum_address(token_address), Web3.to_checksum_address(weth_address), fee).call()
            
            if pool_address != '0x0000000000000000000000000000000000000000':
                
                # Create pool contract instance
                pool_contract = web3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=uniswap_v3_pool_abi)
                
                # Fetch slot0 from the pool contract
                slot0 = pool_contract.functions.slot0().call()
                sqrtPriceX96 = slot0[0]

                # Calculate token price
                token_price = (sqrtPriceX96 ** 2 / (2 ** 192)) * (10 ** token_decimals) / (10 ** 18)
                return token_price, pool_address
        except Exception as e:
            logging.error(f"Error fetching Uniswap V3 price for fee tier {fee}: {e}")
    
    return None, None

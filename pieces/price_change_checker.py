import logging
import os
from datetime import datetime, timedelta, timezone

# Load environment variables
NO_CHANGE_THRESHOLD_PERCENT = float(os.getenv('NO_CHANGE_THRESHOLD_PERCENT')) / 100  # Convert to fraction
NO_CHANGE_TIME_MINUTES = int(os.getenv('NO_CHANGE_TIME_MINUTES'))  # Time in minutes

def check_price_change(current_price, initial_price, start_time, monitoring_id, symbol, token_amount):
    price_increase = (current_price - initial_price) / initial_price
    price_decrease = (initial_price - current_price) / initial_price
    percent_change = ((current_price - initial_price) / initial_price) * 100

    if datetime.now(timezone.utc) - start_time > timedelta(minutes=NO_CHANGE_TIME_MINUTES):
        if abs(price_increase) < NO_CHANGE_THRESHOLD_PERCENT and abs(price_decrease) < NO_CHANGE_THRESHOLD_PERCENT:
            logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — Price did not change significantly in the first {NO_CHANGE_TIME_MINUTES} minutes. Selling the token.")
            return True, token_amount, f'Price did not change significantly in the first {NO_CHANGE_TIME_MINUTES} minutes'
        else:
            logging.info(f"Monitoring {monitoring_id} — Price change threshold breached.")
            return False, None, None

    logging.info(f"Monitoring {monitoring_id} — Current price: {current_price} ETH ({percent_change:.2f}%). — {token_amount} {symbol}.")
    return False, None, None

import logging
import os
from datetime import datetime, timedelta, timezone

# Load environment variables
NO_CHANGE_THRESHOLD_PERCENT = float(os.getenv('NO_CHANGE_THRESHOLD_PERCENT')) / 100  # Convert to fraction
NO_CHANGE_TIME_MINUTES = int(os.getenv('NO_CHANGE_TIME_MINUTES'))  # Time in minutes

def check_no_change_threshold(start_time, price_history, monitoring_id, symbol, token_amount):
    current_time = datetime.now(timezone.utc)
    intervals_passed = (current_time - start_time) // timedelta(minutes=NO_CHANGE_TIME_MINUTES)
    threshold_percent = NO_CHANGE_THRESHOLD_PERCENT * 100  # Convert to percentage for logging

    if intervals_passed > 0:
        for interval in range(intervals_passed):
            interval_start_time = start_time + timedelta(minutes=interval * NO_CHANGE_TIME_MINUTES)
            interval_end_time = interval_start_time + timedelta(minutes=NO_CHANGE_TIME_MINUTES)

            # Filter the price history to only include prices within the current interval
            interval_prices = [price for timestamp, price in price_history if interval_start_time <= timestamp < interval_end_time]

            if not interval_prices:
                continue

            min_price = min(interval_prices)
            max_price = max(interval_prices)
            initial_price = interval_prices[0]
            price_increase = (max_price - initial_price) / initial_price
            price_decrease = (initial_price - min_price) / initial_price

            if abs(price_increase) < NO_CHANGE_THRESHOLD_PERCENT and abs(price_decrease) < NO_CHANGE_THRESHOLD_PERCENT:
                logging.info(f"Monitoring {monitoring_id} — No significant price change — {threshold_percent:.2f}%. — detected in a {NO_CHANGE_TIME_MINUTES} minutes interval. Selling the token.")
                return True, token_amount, f'Price did not change significantly — {threshold_percent:.2f}%. — in a {NO_CHANGE_TIME_MINUTES} minutes interval.', start_time
            else:
                logging.info(f"Monitoring {monitoring_id} — Significant price — {threshold_percent:.2f}%. — in a {NO_CHANGE_TIME_MINUTES} minutes interval. Continuing monitoring.")
                return False, None, None, interval_end_time  # Return the updated start time

    return False, None, None, start_time  # Return the original start time if no intervals passed
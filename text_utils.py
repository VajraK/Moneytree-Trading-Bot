import re

def insert_zero_width_space(text):
    """
    Inserts a zero-width space between each digit in sequences of 9 to 30 digits
    followed by a dot or preceded by a dot.
    """
    zero_width_space = '\u200B'
    
    # Pattern for 9 to 30 digits followed by a dot
    pattern_following_dot = r'(\d{9,30})(\.)'
    # Pattern for 9 to 30 digits preceded by a dot
    pattern_preceding_dot = r'(\.)(\d{9,30})'
    
    def insert_spaces_following_dot(match):
        return zero_width_space.join(match.group(1)) + match.group(2)
    
    def insert_spaces_preceding_dot(match):
        return match.group(1) + zero_width_space.join(match.group(2))
    
    # Apply substitutions
    text = re.sub(pattern_following_dot, insert_spaces_following_dot, text)
    text = re.sub(pattern_preceding_dot, insert_spaces_preceding_dot, text)
    
    return text

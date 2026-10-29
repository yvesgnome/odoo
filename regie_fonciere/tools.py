import re

from dateutil.relativedelta import relativedelta

from odoo.tools.misc import format_date, formatLang


def format_structured_communication(base):
    """ Belgian structured communication (OGM-VCS) from a number of at most 10 digits:
    +++xxx/xxxx/xxxxx+++ where the last 2 digits are the base modulo 97 (97 when 0). """
    digits = str(int(base)).rjust(10, '0')
    if len(digits) > 10:
        raise ValueError("The base of a structured communication has at most 10 digits.")
    check = int(digits) % 97 or 97
    return '+++%s/%s/%s%02d+++' % (digits[:3], digits[3:7], digits[7:], check)


def is_valid_structured_communication(communication):
    """ True if the string is a well-formed Belgian structured communication with a valid check. """
    match = re.fullmatch(r'\+\+\+(\d{3})/(\d{4})/(\d{5})\+\+\+', (communication or '').strip())
    if not match:
        return False
    digits = ''.join(match.groups())
    return (int(digits[:10]) % 97 or 97) == int(digits[10:])


def month_start(date):
    return date.replace(day=1)


def month_end(date):
    return date.replace(day=1) + relativedelta(months=1, days=-1)


def fmt_amount(env, amount, currency):
    """ Amount formatted in the language of the user, with the currency symbol. """
    return formatLang(env, amount, currency_obj=currency)


def fmt_number(env, value, digits=2):
    return formatLang(env, value, digits=digits)


def fmt_date(env, date):
    return format_date(env, date)

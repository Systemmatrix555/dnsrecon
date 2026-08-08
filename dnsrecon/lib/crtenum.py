#    Copyright (C) 2010  Carlos Perez
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; Applies version 2 of the License.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA


import random

import httpx
import stamina
from loguru import logger

__name__ = 'crtenum'

RETRY_ATTEMPTS = 20
WAIT_MAX = 60

COMMON_USER_AGENTS = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0',
)


def is_transient_error(e: Exception) -> bool:
    if isinstance(e, httpx.TimeoutException):
        logger.error(f'Connection with crt.sh failed. Reason: "{e}"')
        return True
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in {429, 500, 502, 503, 504}:
        logger.error(f'Bad http status from crt.sh: "{e.response.status_code}"')
        return True
    logger.error(f'Something went wrong. Reason: "{e}"')
    return False


def _crtsh_candidate_names(entry):
    """
    Yield hostname candidates from a crt.sh JSON entry.

    crt.sh returns both common_name and name_value (SANs). name_value may
    contain multiple names separated by newlines.
    """
    for key in ('common_name', 'name_value'):
        raw = entry.get(key)
        if not raw or not isinstance(raw, str):
            continue
        for name in raw.splitlines():
            name = name.strip().lower().rstrip('.')
            if name:
                yield name


def _crtsh_name_in_scope(name, dom):
    """
    Return a de-wildcarded hostname if it belongs to dom (or is dom itself).
    """
    if name.startswith('*.'):
        logger.info(f'\t {name} wildcard')
        name = name[2:]

    if name == dom or name.endswith('.' + dom):
        return name
    return None


@stamina.retry(on=is_transient_error, attempts=RETRY_ATTEMPTS, wait_max=WAIT_MAX)
def scrape_crtsh(dom):
    """
    Function for enumerating subdomains by querying crt.sh JSON API.
    """
    results = []
    seen = set()
    headers = {'User-Agent': random.choice(COMMON_USER_AGENTS)}
    # Match both the apex and subdomains; %25 is URL-encoded '%'
    url = f'https://crt.sh/?q=%25.{dom}&output=json'

    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception as e:
        logger.error(f'Error parsing JSON from crt.sh: {e}')
        return results

    if not data:
        logger.error('Certificates for subdomains not found')
        return results

    dom = dom.lower().rstrip('.')
    for entry in data:
        for candidate in _crtsh_candidate_names(entry):
            host = _crtsh_name_in_scope(candidate, dom)
            if host and host not in seen:
                seen.add(host)
                results.append(host)

    return results

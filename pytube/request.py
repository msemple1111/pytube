"""Implements a simple wrapper around urlopen."""
import json
import logging
from functools import lru_cache
import re
import socket
from urllib import parse
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen
import asyncio
import aiohttp
from async_property import async_property

from pytube.exceptions import RegexMatchError, MaxRetriesExceeded, PytubeError
from pytube.helpers import regex_search

logger = logging.getLogger(__name__)
default_range_size = 9437184  # 9MB
default_chunk_size = 4096  # 4kb


async def _execute_request(
    url,
    session,
    method="GET",
    headers=None,
    data=None,
    timeout=900
):
    base_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.0 Safari/605.1.15",
        "Accept-Language": "en-gb",
        "Accept": "text/html,application/xhtml+xml,application/json,application/xml,*/*",
        "Cookie": " SIDCC=AJi4QfH98WcrVkkwkemQMRQ9WZk9asesce9uEBJkCoSZx7KTeRNtuzR27BMQI2egTnqm88zh5X8; __Secure-3PSIDCC=AJi4QfFQwZXPSNQg6UMBf5qN10JKZXOo5rF_bNIt49K-rjiVAenqPrDUOIidVRuIVX2VuuXWgTuh; PREF=f6=80&cvdm=grid&tz=Europe.London&al=en&f1=50000000&f5=20030; YSC=LX5Yqn1VDIY; SID=7gcQhFI6EGi5fTesrHcRi7R8Kr7hATYaPzfFKRMKbU683gEa3lCY9Cxwp5Qvx95NzW0iJw.; __Secure-3PSID=7gcQhFI6EGi5fTesrHcRi7R8Kr7hATYaPzfFKRMKbU683gEasPa2dANKe7n6oJFYyNl3zQ.; VISITOR_INFO1_LIVE=yMho0O5Fu8c; LOGIN_INFO=AFmmF2swRgIhAID-B4DkkwhR-1gfK2OiiNzQnI9wvr4u2V8t9t_EelE4AiEA0f9f0va-cI6W4fuiUY1csuXBcGrtMesF0qClM6QKo1Q:QUQ3MjNmd0pST1pxNnZtcjBEeVZaWEIxeTdjd2tSX0NRUG9aS0xMbm9OUjF5cVhWS05pcmZRUlJxTW5xeElUWFZfM25COE5MYUNEbWQtX3YtMVo1elNHSUo5dUxKNk9QSTE4QU1TbXZQQUtiUzBENWhlR2lRVkoyWGRJVmVwRXA5MFdTc2JCNmZoOUZhb0ZaWWYwM19VanlydGZYMjEtMHZxX0FxNF8tbnBwRVIxeVB1dElIdUdDM1g1bGNyV29jT3NSWVAwTVZtRGlM; APISID=9Ypo17XlCCqRQOqg/AGiSpUTfb32XlzW5y; CONSENT=YES+GB.en+20150628-20-0; HSID=AVfH2Ju5Ehm1Mb2fQ; SAPISID=pga-i3racg1AaWor/Au9F8Y1xXPhYV7Wa4; SSID=APSW8jzRJN6bFhee7; __Secure-3PAPISID=pga-i3racg1AaWor/Au9F8Y1xXPhYV7Wa4"}
    if headers:
        base_headers.update(headers)
    # if data:
    #     # encode data for request
    #     data = bytes(json.dumps(data), "utf-8")
    if url.lower().startswith("http"):
        try:
            resp = await session.request(
                    method,
                    url,
                    headers=base_headers,
                    json=data)
            if resp.status == 400:
                raise PytubeError(f"Not 200 code, code={resp.status}")
            else:
                return resp
        except aiohttp.client_exceptions.InvalidURL:
            await session.close()
            raise ValueError("Invalid URL")
    else:
        raise ValueError("Invalid URL")


async def get(url, session, extra_headers=None, timeout=900):
    """Send an http GET request.

    :param str url:
        The URL to perform the GET request for.
    :param dict extra_headers:
        Extra headers to add to the request
    :rtype: str
    :returns:
        UTF-8 encoded string of response
    """
    if extra_headers is None:
        extra_headers = {}
    response = await _execute_request(
        url,
        session,
        method='GET',
        headers=extra_headers,
        timeout=timeout
    )
    return await response.text()


async def post(url, session, extra_headers=None, data=None, timeout=900):
    """Send an http POST request.

    :param str url:
        The URL to perform the POST request for.
    :param dict extra_headers:
        Extra headers to add to the request
    :param dict data:
        The data to send on the POST request
    :rtype: str
    :returns:
        UTF-8 encoded string of response
    """
    # could technically be implemented in get,
    # but to avoid confusion implemented like this
    if extra_headers is None:
        extra_headers = {}
    if data is None:
        data = {}
    # required because the youtube servers are strict on content type
    # raises HTTPError [400]: Bad Request otherwise
    # extra_headers.update({"Content-Type": "application/json"})
    response = await _execute_request(
        url,
        session,
        method='POST',
        headers=extra_headers,
        data=data,
        timeout=timeout
    )
    return await response.text()


async def seq_stream(
    url,
    session,
    timeout=900,
    max_retries=0
):
    """Read the response in sequence.
    :param str url: The URL to perform the GET request for.
    :rtype: Iterable[bytes]
    """
    # YouTube expects a request sequence number as part of the parameters.
    split_url = parse.urlsplit(url)
    base_url = '%s://%s/%s?' % (split_url.scheme, split_url.netloc, split_url.path)

    querys = dict(parse.parse_qsl(split_url.query))

    # The 0th sequential request provides the file headers, which tell us
    #  information about how the file is segmented.
    querys['sq'] = 0
    url = base_url + parse.urlencode(querys)

    segment_data = b''
    async for chunk in stream(url, session, timeout=timeout, max_retries=max_retries):
        yield chunk
        segment_data += chunk

    # We can then parse the header to find the number of segments
    stream_info = segment_data.split(b'\r\n')
    segment_count_pattern = re.compile(b'Segment-Count: (\\d+)')
    for line in stream_info:
        match = segment_count_pattern.search(line)
        if match:
            segment_count = int(match.group(1).decode('utf-8'))

    # We request these segments sequentially to build the file.
    seq_num = 1
    while seq_num <= segment_count:
        # Create sequential request URL
        querys['sq'] = seq_num
        url = base_url + parse.urlencode(querys)

        await stream(url, session, timeout=timeout, max_retries=max_retries)
        seq_num += 1
    return  # pylint: disable=R1711


async def stream(
    url,
    session,
    timeout=900,
    max_retries=0
):
    """Read the response in chunks.
    :param str url: The URL to perform the GET request for.
    :rtype: Iterable[bytes]
    """
    file_size: int = default_range_size  # fake filesize to start
    downloaded = 0
    while downloaded < file_size:
        stop_pos = min(downloaded + default_range_size, file_size) - 1
        range_header = f"bytes={downloaded}-{stop_pos}"
        tries = 0

        # Attempt to make the request multiple times as necessary.
        while True:
            # If the max retries is exceeded, raise an exception
            if tries >= 1 + max_retries:
                raise MaxRetriesExceeded()

            # Try to execute the request, ignoring socket timeouts
            try:
                response = await _execute_request(
                    url,
                    session,
                    method="GET",
                    headers={"Range": range_header},
                    timeout=timeout
                )
            except URLError as e:
                # We only want to skip over timeout errors, and
                # raise any other URLError exceptions
                if isinstance(e.reason, socket.timeout):
                    pass
                else:
                    raise
            else:
                # On a successful request, break from loop
                break
            tries += 1

        if file_size == default_range_size:
            try:
                content_range = response.headers["Content-Range"]
                file_size = int(content_range.split("/")[1])
            except (KeyError, IndexError, ValueError) as e:
                logger.error(e)
        while True:
            chunk = await response.content.read(default_chunk_size)
            if not chunk:
                break
            downloaded += len(chunk)
            yield chunk
    return  # pylint: disable=R1711


@lru_cache()
async def filesize(url, session):
    """Fetch size in bytes of file at given URL

    :param str url: The URL to get the size of
    :returns: int: size in bytes of remote file
    """
    return int((await head(url, session))["content-length"])


@lru_cache()
async def seq_filesize(url, session):
    """Fetch size in bytes of file at given URL from sequential requests

    :param str url: The URL to get the size of
    :returns: int: size in bytes of remote file
    """
    total_filesize = 0
    # YouTube expects a request sequence number as part of the parameters.
    split_url = parse.urlsplit(url)
    base_url = '%s://%s/%s?' % (split_url.scheme, split_url.netloc, split_url.path)
    querys = dict(parse.parse_qsl(split_url.query))

    # The 0th sequential request provides the file headers, which tell us
    #  information about how the file is segmented.
    querys['sq'] = 0
    url = base_url + parse.urlencode(querys)
    response = await _execute_request(
        url, session, method="GET"
    )

    response_value = await response.text()
    # The file header must be added to the total filesize
    total_filesize += len(response_value)

    # We can then parse the header to find the number of segments
    segment_count = 0
    stream_info = response_value.split(b'\r\n')
    segment_regex = b'Segment-Count: (\\d+)'
    for line in stream_info:
        # One of the lines should contain the segment count, but we don't know
        #  which, so we need to iterate through the lines to find it
        try:
            segment_count = int(regex_search(segment_regex, line, 1))
        except RegexMatchError:
            pass

    if segment_count == 0:
        raise RegexMatchError('seq_filesize', segment_regex)

    # We make HEAD requests to the segments sequentially to find the total filesize.
    seq_num = 1
    while seq_num <= segment_count:
        # Create sequential request URL
        querys['sq'] = seq_num
        url = base_url + parse.urlencode(querys)

        total_filesize += int((await head(url, session))['content-length'])
        seq_num += 1
    return total_filesize


async def head(url, session):
    """Fetch headers returned http GET request.

    :param str url:
        The URL to perform the GET request for.
    :rtype: dict
    :returns:
        dictionary of lowercase headers
    """
    response_headers = (await _execute_request(url, session, method="HEAD")).headers
    return {k.lower(): v for k, v in response_headers.items()}

def createSession():
    return aiohttp.ClientSession()